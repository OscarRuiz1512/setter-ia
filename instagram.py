from __future__ import annotations
import httpx
import json
import re
from database import get_db, Conversation, Lead, ConversationStage, Platform, Tenant
from claude_agent import get_ai_response
from whatsapp import send_whatsapp_message

GRAPH_URL = "https://graph.facebook.com/v19.0"


# ── Envío de mensajes de Instagram ──────────────────────────────────────────

def send_instagram_dm(tenant: Tenant, recipient_id: str, text: str):
    """Envía un DM de Instagram a un usuario usando la Graph API."""
    url = f"{GRAPH_URL}/{tenant.instagram_account_id}/messages"
    headers = {
        "Authorization": f"Bearer {tenant.instagram_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    with httpx.Client(timeout=15) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


# ── Procesamiento de eventos de Instagram ───────────────────────────────────

def handle_instagram_dm(tenant: Tenant, sender_id: str, text: str):
    """Procesa un DM entrante de Instagram y responde con la IA."""
    db = get_db()
    try:
        conv = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant.id, user_id=sender_id, platform=Platform.instagram)
            .first()
        )
        if not conv:
            conv = Conversation(
                tenant_id=tenant.id,
                user_id=sender_id,
                platform=Platform.instagram,
                history="[]",
                stage=ConversationStage.opening,
            )
            db.add(conv)
            db.commit()

        if conv.stage == ConversationStage.completed:
            return

        history = json.loads(conv.history)
        history.append({"role": "user", "content": text})

        response, lead_data = get_ai_response(
            history,
            system_prompt=tenant.get_system_prompt(),
            user_id=sender_id,
            platform="instagram",
        )

        history.append({"role": "assistant", "content": response})
        conv.history = json.dumps(history)

        clean_response = re.sub(r"\[\[LEAD_CAPTURED:.*?\]\]", "", response, flags=re.DOTALL).strip()
        send_instagram_dm(tenant, sender_id, clean_response)

        # Detectar si la IA pidió pasar a WhatsApp (busca número en el mensaje del usuario)
        wa_number = _extract_whatsapp_number(text)
        if wa_number and conv.stage == ConversationStage.qualifying:
            conv.stage = ConversationStage.moving_to_wa
            conv.whatsapp_number = wa_number
            db.commit()
            # Inicia conversación en WhatsApp
            _start_whatsapp_conversation(tenant, conv, wa_number)
            return

        if conv.stage == ConversationStage.moving_to_wa:
            wa_number = _extract_whatsapp_number(text)
            if wa_number:
                conv.whatsapp_number = wa_number
                db.commit()
                _start_whatsapp_conversation(tenant, conv, wa_number)
                return

        # Detectar si se debe pedir el WhatsApp
        if _should_request_whatsapp(conv.stage, response):
            conv.stage = ConversationStage.moving_to_wa

        if lead_data:
            _capture_lead(db, tenant, conv, lead_data)
        else:
            if conv.stage == ConversationStage.opening:
                conv.stage = ConversationStage.qualifying

        db.commit()
    finally:
        db.close()


def handle_new_follower(tenant: Tenant, follower_id: str):
    """Envía un DM de bienvenida a un nuevo seguidor."""
    db = get_db()
    try:
        existing = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant.id, user_id=follower_id)
            .first()
        )
        if existing:
            return  # Ya tiene conversación, no spamear

        welcome_message = _generate_welcome_message(tenant)

        conv = Conversation(
            tenant_id=tenant.id,
            user_id=follower_id,
            platform=Platform.instagram,
            history=json.dumps([{"role": "assistant", "content": welcome_message}]),
            stage=ConversationStage.opening,
        )
        db.add(conv)
        db.commit()

        send_instagram_dm(tenant, follower_id, welcome_message)
    finally:
        db.close()


def handle_post_comment(tenant: Tenant, commenter_id: str, comment_text: str, post_id: str):
    """Responde con un DM a alguien que comenta en un post."""
    db = get_db()
    try:
        existing = (
            db.query(Conversation)
            .filter_by(tenant_id=tenant.id, user_id=commenter_id)
            .first()
        )
        if existing:
            return  # Ya tiene conversación activa

        context_message = (
            f"Vi que comentaste en el post, quería escribirte personalmente. "
            f"¿Tienes algún objetivo de transformación física en mente? "
            f"Puedo ayudarte a ver si nuestro programa encaja contigo 💪"
        )

        conv = Conversation(
            tenant_id=tenant.id,
            user_id=commenter_id,
            platform=Platform.instagram,
            history=json.dumps([
                {"role": "user", "content": f"[Comentó en post]: {comment_text}"},
                {"role": "assistant", "content": context_message},
            ]),
            stage=ConversationStage.opening,
        )
        db.add(conv)
        db.commit()

        send_instagram_dm(tenant, commenter_id, context_message)
    finally:
        db.close()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _extract_whatsapp_number(text: str) -> str | None:
    """Detecta un número de teléfono en el texto del usuario."""
    match = re.search(r"(\+?[\d\s\-\(\)]{9,15})", text)
    if match:
        number = re.sub(r"[\s\-\(\)]", "", match.group(1))
        if len(number) >= 9:
            return number
    return None


def _should_request_whatsapp(stage: str, ai_response: str) -> bool:
    """Detecta si la IA ya está pidiendo el número de WhatsApp."""
    keywords = ["whatsapp", "wasap", "número", "numero", "contacto", "teléfono", "telefono"]
    response_lower = ai_response.lower()
    return any(kw in response_lower for kw in keywords)


def _generate_welcome_message(tenant: Tenant) -> str:
    """Genera el mensaje de bienvenida para un nuevo seguidor."""
    return (
        f"¡Hola! Gracias por seguirnos 🙌 "
        f"Me alegra tenerte aquí. ¿Tienes algún objetivo de transformación física "
        f"que estés buscando conseguir? Cuéntame, estoy para ayudarte 💪"
    )


def _start_whatsapp_conversation(tenant: Tenant, conv: Conversation, wa_number: str):
    """Inicia la conversación de seguimiento en WhatsApp."""
    db = get_db()
    try:
        history = json.loads(conv.history)
        context_summary = _summarize_context(history)

        intro = (
            f"¡Hola {conv.name or ''}! 👋 Soy {tenant.setter_name or 'Alex'}, "
            f"te escribo desde WhatsApp como te dije por Instagram.\n\n"
            f"{context_summary}\n\n"
            f"¿Cuándo tienes 20 minutos para una llamada rápida sin compromiso? "
            f"Te cuento exactamente cómo funciona el programa 🚀"
        )

        if tenant.calendly_link:
            intro += f"\n\nPuedes elegir el horario que mejor te venga aquí: {tenant.calendly_link}"

        send_whatsapp_message(tenant, wa_number, intro)

        # Crear conversación de WhatsApp en la BD
        wa_conv = Conversation(
            tenant_id=tenant.id,
            user_id=wa_number,
            platform=Platform.whatsapp,
            history=json.dumps([{"role": "assistant", "content": intro}]),
            stage=ConversationStage.scheduling,
            name=conv.name,
            goal=conv.goal,
        )
        db.add(wa_conv)
        conv.stage = ConversationStage.moving_to_wa
        db.commit()
    finally:
        db.close()


def _summarize_context(history: list) -> str:
    """Resume brevemente lo hablado en Instagram para retomar en WhatsApp."""
    goals = []
    for msg in history:
        if msg["role"] == "user":
            text = msg["content"].lower()
            if any(kw in text for kw in ["perder", "ganar", "músculo", "grasa", "correr", "fuerza", "salud"]):
                goals.append(msg["content"][:100])

    if goals:
        return f"Recuerdo que me contaste que tu objetivo es: {goals[0]}"
    return "Me alegra seguir con nuestra conversación de Instagram."


def _capture_lead(db, tenant: Tenant, conv: Conversation, lead_data: dict):
    """Guarda el lead en la BD y notifica al owner."""
    lead = Lead(
        tenant_id=tenant.id,
        platform=conv.platform,
        user_id=conv.user_id,
        name=lead_data.get("name", ""),
        email=lead_data.get("email", ""),
        goal=lead_data.get("goal", ""),
        whatsapp_number=lead_data.get("whatsapp", conv.whatsapp_number),
    )
    db.add(lead)
    conv.stage = ConversationStage.completed
    conv.name = lead_data.get("name")
    conv.email = lead_data.get("email")
    conv.goal = lead_data.get("goal")

    if tenant.owner_whatsapp:
        _notify_owner(tenant, lead)

    db.commit()


def _notify_owner(tenant: Tenant, lead: Lead):
    """Notifica al coach/owner cuando se captura un lead."""
    msg = (
        f"🎯 *Nuevo Lead Calificado — {tenant.name}*\n\n"
        f"👤 Nombre: {lead.name or 'N/A'}\n"
        f"📧 Email: {lead.email or 'N/A'}\n"
        f"📱 WhatsApp: {lead.whatsapp_number or 'N/A'}\n"
        f"🏋️ Objetivo: {lead.goal or 'N/A'}\n"
        f"📲 Plataforma: {lead.platform}"
    )
    try:
        send_whatsapp_message(tenant, tenant.owner_whatsapp, msg)
    except Exception:
        pass
