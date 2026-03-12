import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.schemas.organisation import RoleInOrg


class AccountMemberRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID
    role_in_org: str
    access_all: bool
    created_at: datetime
    user_email: str | None = None
    user_full_name: str | None = None
    organisation_names: list[str] = []


class AccountMemberUpdate(BaseModel):
    role_in_org: RoleInOrg | None = None
    access_all: bool | None = None
    organisation_ids: list[uuid.UUID] | None = None


class AccountInvitationCreate(BaseModel):
    email: EmailStr
    role_in_org: RoleInOrg = RoleInOrg.USER
    access_all: bool = True
    organisation_ids: list[uuid.UUID] | None = None
