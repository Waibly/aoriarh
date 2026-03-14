import uuid
from datetime import datetime

from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


class ProfilMetier(StrEnum):
    DRH = "drh"
    CHARGE_RH = "charge_rh"
    ELU_CSE = "elu_cse"
    DIRIGEANT = "dirigeant"
    JURISTE = "juriste"
    CONSULTANT_RH = "consultant_rh"


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "user"


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    auth_provider: str = "credentials"
    profil_metier: str | None = None
    plan: str | None = None
    plan_expires_at: datetime | None = None
    workspace_name: str | None = None
    workspace_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    profil_metier: ProfilMetier | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)
