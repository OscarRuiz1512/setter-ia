import os
import re
import json
import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """Eres Alex, un asistente de ventas de planes de entrenamiento y nutrición personalizados.

Tu misión es seguir este flujo de forma natural:
1. Saluda de forma cálida y pregunta cuál es su objetivo fitness.
2. Haz preguntas de calificación (máximo 2 por mensaje):
   - Objetivo principal (perder grasa, ganar músculo, mejorar rendimiento, salud general…)
   - Nivel de experiencia (principiante, intermedio, avanzado)
   - Días disponibles para entrenar
   - Alguna lesión o restricción alimentaria relevante
3. Explica brevemente que tenéis planes 100% personalizados de entrenamiento + nutrición.
4. Recoge los datos de contacto para que el equipo le llame:
   - Nombre completo
   - Email
5. Cierra la conversación con positividad, indicando que el equipo le contactará pronto.

Cuando tengas nombre, email y objetivo, añade al FINAL de tu respuesta (sin nada después):
[[LEAD_CAPTURED:{"name": "NOMBRE", "email": "EMAIL", "goal": "OBJETIVO_RESUMIDO"}]]

REGLAS:
- Habla siempre en español, de forma cercana y motivadora.
- Mensajes cortos y naturales, como un chat real de WhatsApp.
- No inventes precios, el equipo informará personalmente.
- Si alguien no está interesado, sé amable y deja la puerta abierta.
- No repitas preguntas que ya hayas hecho."""

model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    system_instruction=SYSTEM_PROMPT,
)


def get_ai_response(history: list, phone_number: str) -> tuple[str, dict | None]:
    # Convert history format: "assistant" → "model" (Gemini format)
    gemini_history = []
    for msg in history[:-1]:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    chat = model.start_chat(history=gemini_history)
    response = chat.send_message(history[-1]["content"])
    content = response.text
    lead_data = None

    match = re.search(r"\[\[LEAD_CAPTURED:(.*?)\]\]", content, re.DOTALL)
    if match:
        try:
            lead_data = json.loads(match.group(1))
            lead_data["phone"] = phone_number
        except json.JSONDecodeError:
            pass

    return content, lead_data
