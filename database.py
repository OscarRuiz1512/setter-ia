import os
from sqlalchemy import create_engine, Column, String, Text, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"

    phone_number = Column(String, primary_key=True)
    history = Column(Text, default="[]")
    stage = Column(String, default="active")  # active | completed
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    goal = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True)
    phone_number = Column(String)
    name = Column(String)
    email = Column(String)
    goal = Column(String)
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    return SessionLocal()
