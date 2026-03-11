import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.schemas.organisation import RoleInOrg


class InvitationCreate(BaseModel):
    email: EmailStr
    role_in_org: RoleInOrg = RoleInOrg.USER


class InvitationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    organisation_id: uuid.UUID
    invited_by: uuid.UUID
    role_in_org: str
    token: uuid.UUID
    status: str
    expires_at: datetime
    created_at: datetime
    organisation_name: str | None = None
    inviter_name: str | None = None


class InvitationValidateResponse(BaseModel):
    valid: bool
    email: str | None = None
    organisation_name: str | None = None
    status: str | None = None
