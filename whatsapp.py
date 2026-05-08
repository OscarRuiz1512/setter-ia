from __future__ import annotations
import re
import json
import httpx
from database import get_db, Conversation, Lead, ConversationStage, Platform, Tenant
from claude_agent import get_ai_response

GRAPH_URL = "https://graph.facebook.com/v19.0"


# ── Envío de mensajes ────────────────────────────────────────────────────────

def send_whatsapp_message(tenant: Tenant, phone_number: str, text: str):
    """Envía un mensaje de WhatsApp usando la Cloud API de Meta."""
    url = f"{GRAPH_URL}/{tenant.whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {tenant.whatsapp_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "text",
        "text": {"body": text},
    }
    with httpx.Client(timeout=15) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


# ── Procesamiento de mensajes entrantes ─────────────────────────────────────

def handle_whatsapp_message(tenant: Tenant, phone_number: str, text: str):
    """Procesa un mensaje de WhatsApp entrante y responde con la IA."""
    db = get_db()
    try:
        conv = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant.id, user_id=phone_number, platform=Platform.whatsapp)
            .first()
        )
        if not conv:
            conv = Conversation(
                tenant_id=tenant.id,
                user_id=phone_number,
                platform=Platform.whatsapp,
                history="[]",
                stage=ConversationStage.scheduling,
            )
            db.add(conv)
            db.commit()

        if conv.stage == ConversationStage.completed:
            send_whatsapp_message(
                tenant,
                phone_number,
                "¡Ya tenemos todos tus datos! El equipo se pondrá en contacto contigo muy pronto 💪",
            )
            return

        history = json.loads(conv.history)
        history.append({"role": "user", "content": text})

        response, lead_data = get_ai_response(
            history,
            system_prompt=tenant.get_system_prompt(),
            user_id=phone_number,
            platform="whatsapp",
        )

        history.append({"role": "assistant", "content": response})
        conv.history = json.dumps(history)

        clean_response = re.sub(r"\[\[LEAD_CAPTURED:.*?\]\]", "", response, flags=re.DOTALL).strip()
        send_whatsapp_message(tenant, phone_number, clean_response)

        if lead_data:
            lead = Lead(
                tenant_id=tenant.id,
                platform=Platform.whatsapp,
                user_id=phone_number,
                name=lead_data.get("name", ""),
                email=lead_data.get("email", ""),
                goal=lead_data.get("goal", ""),
                whatsapp_number=phone_number,
            )
            db.add(lead)
            conv.stage = ConversationStage.completed
            conv.name = lead_data.get("name")
            conv.email = lead_data.get("email")
            conv.goal = lead_data.get("goal")

            if tenant.owner_whatsapp and tenant.owner_whatsapp != phone_number:
                _notify_owner_whatsapp(tenant, lead, phone_number)

        db.commit()
    finally:
        db.close()


def _notify_owner_whatsapp(tenant: Tenant, lead: Lead, phone_number: str):
    msg = (
        f"🎯 *Nuevo Lead — {tenant.name}*\n\n"
        f"👤 Nombre: {lead.name or 'N/A'}\n"
        f"📧 Email: {lead.email or 'N/A'}\n"
        f"📱 WhatsApp: {phone_number}\n"
        f"🏋️ Objetivo: {lead.goal or 'N/A'}"
    )
    try:
        send_whatsapp_message(tenant, tenant.owner_whatsapp, msg)
    except Exception:
        pass
