from __future__ import annotations
import os
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from database import get_db, Tenant, init_db
from admin import router as admin_router
from instagram import handle_instagram_dm, handle_new_follower, handle_post_comment
from whatsapp import handle_whatsapp_message

load_dotenv()

app = FastAPI(title="Setter IA — Plataforma Multi-tenant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.mount("/panel", StaticFiles(directory="admin_panel", html=True), name="panel")
app.mount("/landing", StaticFiles(directory="landing"), name="landing")


@app.on_event("startup")
def startup():
    init_db()
    _auto_create_admin()


def _auto_create_admin():
    """Crea o actualiza el admin desde las variables de entorno en cada arranque."""
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    from database import AdminUser
    import secrets, hashlib
    db = get_db()
    try:
        admin = db.query(AdminUser).filter_by(email=email.lower().strip()).first()
        if admin:
            salt = secrets.token_hex(32)
            admin.salt = salt
            admin.password_hash = AdminUser.hash_password(password, salt)
        else:
            admin = AdminUser.create(email=email, password=password)
            db.add(admin)
        db.commit()
        print(f"[Setter IA] Admin sincronizado: {email}")
    except Exception as e:
        print(f"[Setter IA] Error al sincronizar admin: {e}")
    finally:
        db.close()


# ── Helpers de tenant ────────────────────────────────────────────────────────

def _get_tenant_by_instagram(account_id: str) -> Tenant | None:
    db = get_db()
    try:
        return db.query(Tenant).filter_by(
            instagram_account_id=account_id, is_active=True
        ).first()
    finally:
        db.close()


def _get_tenant_by_whatsapp(phone_id: str) -> Tenant | None:
    db = get_db()
    try:
        return db.query(Tenant).filter_by(
            whatsapp_phone_id=phone_id, is_active=True
        ).first()
    finally:
        db.close()


# ── Webhook de Instagram ─────────────────────────────────────────────────────

@app.get("/webhook/instagram")
async def verify_instagram_webhook(request: Request):
    """Meta verifica el webhook con este endpoint al configurarlo."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = os.getenv("META_VERIFY_TOKEN", "setter_ia_verify")
    if mode == "subscribe" and token == verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook/instagram")
async def instagram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de Instagram: DMs, nuevos seguidores, comentarios."""
    data = await request.json()

    for entry in data.get("entry", []):
        account_id = entry.get("id")
        tenant = _get_tenant_by_instagram(account_id)
        if not tenant:
            continue

        # Mensajes directos
        for messaging in entry.get("messaging", []):
            sender_id = messaging.get("sender", {}).get("id")
            if not sender_id or sender_id == account_id:
                continue

            message = messaging.get("message", {})
            if message and message.get("text"):
                background_tasks.add_task(
                    handle_instagram_dm, tenant, sender_id, message["text"]
                )

        # Cambios de página (nuevos seguidores, comentarios)
        for change in entry.get("changes", []):
            field = change.get("field")
            value = change.get("value", {})

            if field == "follow":
                follower_id = value.get("sender_id")
                if follower_id:
                    background_tasks.add_task(handle_new_follower, tenant, follower_id)

            elif field == "comments":
                commenter_id = value.get("from", {}).get("id")
                comment_text = value.get("message", "")
                post_id = value.get("media", {}).get("id", "")
                if commenter_id and commenter_id != account_id:
                    background_tasks.add_task(
                        handle_post_comment, tenant, commenter_id, comment_text, post_id
                    )

    return {"status": "ok"}


# ── Webhook de WhatsApp ──────────────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """Meta verifica el webhook de WhatsApp."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = os.getenv("META_VERIFY_TOKEN", "setter_ia_verify")
    if mode == "subscribe" and token == verify_token:
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibe mensajes entrantes de WhatsApp."""
    data = await request.json()

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id")
                messages = value.get("messages", [])

                if not phone_id or not messages:
                    continue

                tenant = _get_tenant_by_whatsapp(phone_id)
                if not tenant:
                    continue

                for message in messages:
                    if message.get("type") != "text":
                        continue
                    phone_number = message["from"]
                    text = message["text"]["body"]
                    background_tasks.add_task(
                        handle_whatsapp_message, tenant, phone_number, text
                    )
    except (KeyError, TypeError):
        pass

    return {"status": "ok"}


# ── Panel de administración ──────────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse("landing/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
