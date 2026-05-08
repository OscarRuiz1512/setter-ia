from __future__ import annotations
import os
import re
import json
import anthropic

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def get_ai_response(
    history: list,
    system_prompt: str,
    user_id: str,
    platform: str = "instagram",
) -> tuple[str, dict | None]:
    """
    Genera la respuesta del setter IA usando Claude.

    Returns:
        (response_text, lead_data_or_None)
    """
    client = get_client()

    # Construye mensajes en formato Anthropic
    messages = []
    for msg in history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=messages,
    )

    content = response.content[0].text
    lead_data = None

    match = re.search(r"\[\[LEAD_CAPTURED:(.*?)\]\]", content, re.DOTALL)
    if match:
        try:
            lead_data = json.loads(match.group(1))
            lead_data["user_id"] = user_id
            lead_data["platform"] = platform
        except json.JSONDecodeError:
            pass

    return content, lead_data


def retrain_prompt(current_prompt: str, feedback: str) -> str:
    """
    Mejora el system prompt de un tenant basándose en feedback del setter humano.
    Permite 'reeducar' la IA con el proceso real de setting.
    """
    client = get_client()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=(
            "Eres un experto en ventas y copywriting de alto rendimiento. "
            "Tu tarea es mejorar prompts de sistemas de IA para setters de ventas. "
            "Devuelve ÚNICAMENTE el prompt mejorado, sin explicaciones ni comentarios."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Este es el prompt actual de mi setter IA:\n\n"
                    f"---\n{current_prompt}\n---\n\n"
                    f"Este es el feedback / corrección que quiero aplicar:\n\n"
                    f"{feedback}\n\n"
                    f"Devuélveme el prompt actualizado incorporando este feedback, "
                    f"manteniendo el resto del flujo intacto."
                ),
            }
        ],
    )

    return response.content[0].text
