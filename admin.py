from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt

from database import get_db, Tenant, Conversation, Lead, AdminUser
from claude_agent import retrain_prompt

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "setter-ia-secret-key-2024")

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBearer()


# ── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class SetupRequest(BaseModel):
    email: str
    password: str


@router.get("/setup-required")
def setup_required():
    """Devuelve true si no hay ningún admin registrado todavía."""
    db = get_db()
    try:
        exists = db.query(AdminUser).first()
        return {"setup_required": exists is None}
    finally:
        db.close()


@router.post("/setup")
def setup(body: SetupRequest):
    """Crea la primera cuenta de administrador (solo funciona si no existe ninguna)."""
    db = get_db()
    try:
        if db.query(AdminUser).first():
            raise HTTPException(status_code=400, detail="Ya existe una cuenta de administrador")
        if not body.email or not body.password:
            raise HTTPException(status_code=400, detail="Email y contraseña son obligatorios")
        if len(body.password) < 6:
            raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
        admin = AdminUser.create(email=body.email, password=body.password)
        db.add(admin)
        db.commit()
        token = jwt.encode(
            {"sub": admin.email, "exp": datetime.utcnow() + timedelta(days=7)},
            SECRET_KEY, algorithm="HS256",
        )
        return {"access_token": token, "token_type": "bearer"}
    finally:
        db.close()


@router.post("/login")
def login(body: LoginRequest):
    db = get_db()
    try:
        admin = db.query(AdminUser).filter_by(email=body.email.lower().strip()).first()
        if not admin or not admin.verify_password(body.password):
            raise HTTPException(status_code=401, detail="Email o contraseña incorrectos")
        token = jwt.encode(
            {"sub": admin.email, "exp": datetime.utcnow() + timedelta(days=7)},
            SECRET_KEY, algorithm="HS256",
        )
        return {"access_token": token, "token_type": "bearer"}
    finally:
        db.close()


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


# ── Schemas ───────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str
    business_type: str = "fitness"
    instagram_account_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None
    whatsapp_token: Optional[str] = None
    whatsapp_number: Optional[str] = None
    setter_name: str = "Alex"
    calendly_link: Optional[str] = None
    owner_whatsapp: Optional[str] = None
    system_prompt: Optional[str] = None
    plan: str = "basic"


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    instagram_account_id: Optional[str] = None
    instagram_access_token: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None
    whatsapp_token: Optional[str] = None
    whatsapp_number: Optional[str] = None
    setter_name: Optional[str] = None
    calendly_link: Optional[str] = None
    owner_whatsapp: Optional[str] = None
    system_prompt: Optional[str] = None
    plan: Optional[str] = None


class RetrainRequest(BaseModel):
    feedback: str


# ── Endpoints: Tenants ────────────────────────────────────────────────────────

@router.get("/tenants")
def list_tenants(_=Depends(require_auth)):
    db = get_db()
    try:
        tenants = db.query(Tenant).all()
        return [_tenant_to_dict(t) for t in tenants]
    finally:
        db.close()


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreate, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = Tenant(
            id=str(uuid.uuid4()),
            name=body.name,
            business_type=body.business_type,
            instagram_account_id=body.instagram_account_id,
            instagram_access_token=body.instagram_access_token,
            whatsapp_phone_id=body.whatsapp_phone_id,
            whatsapp_token=body.whatsapp_token,
            whatsapp_number=body.whatsapp_number,
            setter_name=body.setter_name,
            calendly_link=body.calendly_link,
            owner_whatsapp=body.owner_whatsapp,
            system_prompt=body.system_prompt,
            plan=body.plan,
            is_active=True,
            subscription_start=datetime.utcnow(),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return _tenant_to_dict(tenant)
    finally:
        db.close()


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        leads_count = db.query(Lead).filter_by(tenant_id=tenant_id).count()
        convs_count = db.query(Conversation).filter_by(tenant_id=tenant_id).count()
        data = _tenant_to_dict(tenant)
        data["stats"] = {"leads": leads_count, "conversations": convs_count}
        return data
    finally:
        db.close()


@router.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: str, body: TenantUpdate, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(tenant, field, value)
        tenant.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(tenant)
        return _tenant_to_dict(tenant)
    finally:
        db.close()


@router.delete("/tenants/{tenant_id}", status_code=204)
def delete_tenant(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        db.delete(tenant)
        db.commit()
    finally:
        db.close()


# ── Endpoints: Suscripción ────────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/activate")
def activate_tenant(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        tenant.is_active = True
        tenant.subscription_start = datetime.utcnow()
        tenant.updated_at = datetime.utcnow()
        db.commit()
        return {"message": f"Cliente '{tenant.name}' activado correctamente", "is_active": True}
    finally:
        db.close()


@router.post("/tenants/{tenant_id}/deactivate")
def deactivate_tenant(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        tenant.is_active = False
        tenant.subscription_end = datetime.utcnow()
        tenant.updated_at = datetime.utcnow()
        db.commit()
        return {"message": f"Cliente '{tenant.name}' desactivado correctamente", "is_active": False}
    finally:
        db.close()


# ── Endpoints: Leads ──────────────────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/leads")
def get_leads(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        leads = db.query(Lead).filter_by(tenant_id=tenant_id).order_by(Lead.created_at.desc()).all()
        return [
            {
                "id": l.id,
                "name": l.name,
                "email": l.email,
                "goal": l.goal,
                "whatsapp_number": l.whatsapp_number,
                "platform": l.platform,
                "call_scheduled": l.call_scheduled,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ]
    finally:
        db.close()


@router.get("/leads")
def get_all_leads(_=Depends(require_auth)):
    db = get_db()
    try:
        leads = db.query(Lead).order_by(Lead.created_at.desc()).all()
        tenants = {t.id: t.name for t in db.query(Tenant).all()}
        return [
            {
                "id": l.id,
                "tenant": tenants.get(l.tenant_id, "Desconocido"),
                "name": l.name,
                "email": l.email,
                "goal": l.goal,
                "whatsapp_number": l.whatsapp_number,
                "platform": l.platform,
                "call_scheduled": l.call_scheduled,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in leads
        ]
    finally:
        db.close()


# ── Endpoints: IA / Reentrenamiento ──────────────────────────────────────────

@router.post("/tenants/{tenant_id}/retrain")
def retrain_tenant_ai(tenant_id: str, body: RetrainRequest, _=Depends(require_auth)):
    """Mejora el prompt del setter IA de un cliente con feedback del setter humano."""
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")

        current_prompt = tenant.get_system_prompt()
        new_prompt = retrain_prompt(current_prompt, body.feedback)

        tenant.system_prompt = new_prompt
        tenant.updated_at = datetime.utcnow()
        db.commit()

        return {"message": "Prompt actualizado correctamente", "new_prompt": new_prompt}
    finally:
        db.close()


@router.get("/tenants/{tenant_id}/prompt")
def get_tenant_prompt(tenant_id: str, _=Depends(require_auth)):
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        return {"prompt": tenant.get_system_prompt()}
    finally:
        db.close()


@router.put("/tenants/{tenant_id}/prompt")
def set_tenant_prompt(tenant_id: str, body: RetrainRequest, _=Depends(require_auth)):
    """Sobreescribe el prompt del setter IA directamente."""
    db = get_db()
    try:
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        tenant.system_prompt = body.feedback
        tenant.updated_at = datetime.utcnow()
        db.commit()
        return {"message": "Prompt actualizado"}
    finally:
        db.close()


# ── Helper ────────────────────────────────────────────────────────────────────

def _tenant_to_dict(t: Tenant) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "business_type": t.business_type,
        "setter_name": t.setter_name,
        "is_active": t.is_active,
        "plan": t.plan,
        "has_instagram": bool(t.instagram_account_id),
        "has_whatsapp": bool(t.whatsapp_phone_id),
        "instagram_account_id": t.instagram_account_id,
        "whatsapp_phone_id": t.whatsapp_phone_id,
        "whatsapp_number": t.whatsapp_number,
        "calendly_link": t.calendly_link,
        "owner_whatsapp": t.owner_whatsapp,
        "subscription_start": t.subscription_start.isoformat() if t.subscription_start else None,
        "subscription_end": t.subscription_end.isoformat() if t.subscription_end else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
