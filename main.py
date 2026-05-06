import os
import re
import json
import uuid
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from database import get_db, Conversation, Lead, init_db
from whatsapp import send_message
from claude_agent import get_ai_response

load_dotenv()

app = FastAPI()


@app.on_event("startup")
def startup():
    init_db()


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == os.getenv("VERIFY_TOKEN"):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Token inválido")


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    try:
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        phone_number = message["from"]

        if message["type"] != "text":
            return {"status": "ok"}

        text = message["text"]["body"]
        background_tasks.add_task(process_message, phone_number, text)
    except (KeyError, IndexError):
        pass

    return {"status": "ok"}


def process_message(phone_number: str, text: str):
    db = get_db()
    try:
        conv = db.query(Conversation).filter_by(phone_number=phone_number).first()
        if not conv:
            conv = Conversation(phone_number=phone_number, history="[]")
            db.add(conv)
            db.commit()

        if conv.stage == "completed":
            send_message(
                phone_number,
                "¡Ya tenemos tus datos! En breve nos pondremos en contacto contigo. 💪",
            )
            return

        history = json.loads(conv.history)
        history.append({"role": "user", "content": text})

        response, lead_data = get_ai_response(history, phone_number)

        history.append({"role": "assistant", "content": response})
        conv.history = json.dumps(history)

        # Strip marker before sending to user
        clean_response = re.sub(r"\[\[LEAD_CAPTURED:.*?\]\]", "", response, flags=re.DOTALL).strip()
        send_message(phone_number, clean_response)

        if lead_data:
            lead = Lead(
                id=str(uuid.uuid4()),
                phone_number=phone_number,
                name=lead_data.get("name", ""),
                email=lead_data.get("email", ""),
                goal=lead_data.get("goal", ""),
            )
            db.add(lead)
            conv.stage = "completed"
            conv.name = lead_data.get("name")
            conv.email = lead_data.get("email")
            conv.goal = lead_data.get("goal")

            owner = os.getenv("OWNER_PHONE_NUMBER")
            if owner:
                send_message(
                    owner,
                    f"🎯 *Nuevo Lead Calificado*\n\n"
                    f"👤 Nombre: {lead_data.get('name', 'N/A')}\n"
                    f"📧 Email: {lead_data.get('email', 'N/A')}\n"
                    f"📱 Teléfono: {phone_number}\n"
                    f"🏋️ Objetivo: {lead_data.get('goal', 'N/A')}",
                )

        db.commit()
    finally:
        db.close()
