import os
import uuid
import hashlib
import secrets
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, DateTime,
    Boolean, ForeignKey, Enum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import enum

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./setter_ia.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Platform(str, enum.Enum):
    instagram = "instagram"
    whatsapp = "whatsapp"


class ConversationStage(str, enum.Enum):
    opening = "opening"         # Inicio, primer contacto
    qualifying = "qualifying"   # Preguntas de cualificación
    moving_to_wa = "moving_to_wa"  # Pidiendo pasar a WhatsApp
    scheduling = "scheduling"   # En WhatsApp, agendando llamada
    completed = "completed"     # Lead capturado


class Tenant(Base):
    """Un cliente de la agencia (coach, negocio de fitness, etc.)"""
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    business_type = Column(String, default="fitness")

    # Instagram credentials (Meta Graph API)
    instagram_account_id = Column(String, unique=True, nullable=True)
    instagram_access_token = Column(Text, nullable=True)

    # WhatsApp credentials (Meta Cloud API)
    whatsapp_phone_id = Column(String, unique=True, nullable=True)
    whatsapp_token = Column(Text, nullable=True)
    whatsapp_number = Column(String, nullable=True)

    # Configuración del setter IA
    system_prompt = Column(Text, nullable=True)
    setter_name = Column(String, default="Alex")
    calendly_link = Column(String, nullable=True)
    owner_whatsapp = Column(String, nullable=True)  # Número del coach para notificar leads

    # Suscripción
    is_active = Column(Boolean, default=True)
    plan = Column(String, default="basic")  # basic | pro | enterprise
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", back_populates="tenant", cascade="all, delete")
    leads = relationship("Lead", back_populates="tenant", cascade="all, delete")

    def get_system_prompt(self) -> str:
        """Devuelve el prompt del sistema. Usa el personalizado si existe, si no el genérico."""
        if self.system_prompt:
            return self.system_prompt
        return DEFAULT_SYSTEM_PROMPT.format(
            setter_name=self.setter_name or "Alex",
            calendly_link=self.calendly_link or "[link de calendario]",
        )


class Conversation(Base):
    """Conversación entre el setter IA y un potencial cliente."""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    platform = Column(String, default=Platform.instagram)
    user_id = Column(String, nullable=False)  # Instagram user ID o WhatsApp phone
    history = Column(Text, default="[]")
    stage = Column(String, default=ConversationStage.opening)

    # Datos recopilados del lead
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    goal = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="conversations")


class Lead(Base):
    """Lead cualificado y listo para el closer."""
    __tablename__ = "leads"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    platform = Column(String, default=Platform.instagram)
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    goal = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)
    call_scheduled = Column(Boolean, default=False)
    notified = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="leads")


class AdminUser(Base):
    """Cuenta de administrador de la agencia."""
    __tablename__ = "admin_users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    salt = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()

    @classmethod
    def create(cls, email: str, password: str) -> "AdminUser":
        salt = secrets.token_hex(32)
        return cls(
            email=email.lower().strip(),
            password_hash=cls.hash_password(password, salt),
            salt=salt,
        )

    def verify_password(self, password: str) -> bool:
        return self.hash_password(password, self.salt) == self.password_hash


DEFAULT_SYSTEM_PROMPT = """Eres {setter_name}, un setter de ventas de programas de transformación física.
Tu trabajo es abrir conversaciones, cualificar leads y moverlos a WhatsApp para agendar una llamada de ventas.

FLUJO DE SETTING:

FASE 1 - APERTURA (Instagram):
- Saluda de forma cálida y cercana, como si fuera un mensaje personal.
- Pregunta por su objetivo o qué les llevó a seguir el perfil.
- Sé breve: máximo 2-3 líneas por mensaje.

FASE 2 - CUALIFICACIÓN (máximo 2 preguntas por mensaje):
Recopila (en orden natural, no como formulario):
• Objetivo principal (perder grasa, ganar músculo, mejorar salud, rendimiento...)
• Situación actual (experiencia, qué ha probado antes)
• Disponibilidad (días por semana, tiempo)
• Restricciones relevantes (lesiones, intolerancias)

FASE 3 - PASO A WHATSAPP:
Cuando tengas suficiente información para saber que es un lead cualificado, pide su número de WhatsApp de forma natural:
"Por cierto, ¿tienes WhatsApp? Así te puedo enviar más info personalizada y si te interesa coordinamos una llamada rápida sin compromiso 🙌"

Cuando tengas el número, confirma que le escribirás y cierra la conversación de Instagram.

FASE 4 - WHATSAPP (agendamiento):
- Retoma la conversación resumiendo lo que ya sabes de él/ella.
- Presenta brevemente el programa de transformación.
- Propón agendar una llamada: usa este link → {calendly_link}
- Recoge nombre y email para confirmar.

Cuando tengas nombre, email y objetivo, añade AL FINAL (sin nada después):
[[LEAD_CAPTURED:{{"name": "NOMBRE", "email": "EMAIL", "goal": "OBJETIVO", "whatsapp": "NUMERO_WA"}}]]

REGLAS SIEMPRE:
- Español, tono cercano y motivador. Como un amigo que sabe de fitness.
- Mensajes cortos, naturales. Nada de textos largos.
- No inventes precios. El closer informará en la llamada.
- Si no está interesado, sé amable y deja la puerta abierta.
- No repitas preguntas ya hechas.
- Emojis con moderación (1-2 por mensaje máximo).
"""


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    return SessionLocal()
