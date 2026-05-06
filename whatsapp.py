import os
import httpx

GRAPH_URL = "https://graph.facebook.com/v19.0"


def send_message(phone_number: str, text: str):
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

    url = f"{GRAPH_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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
