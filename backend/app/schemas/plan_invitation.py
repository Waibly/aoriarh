import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class PlanInvitationCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    plan: str = "invite"
    duration_months: int = Field(default=1, ge=1, le=12)
    email: EmailStr | None = None
    max_uses: int | None = Field(default=None, ge=1)
    expires_in_days: int = Field(default=30, ge=1, le=365)


class PlanInvitationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    token: uuid.UUID
    label: str
    plan: str
    duration_months: int
    email: str | None = None
    max_uses: int | None = None
    use_count: int
    status: str
    expires_at: datetime
    created_at: datetime
    shareable_url: str | None = None


class RedemptionItem(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None = None
    user_name: str | None = None
    redeemed_at: datetime


class PlanInvitationDetail(PlanInvitationRead):
    redemptions: list[RedemptionItem] = []


class PlanInvitationValidateResponse(BaseModel):
    valid: bool
    reason: str | None = None
    plan: str | None = None
    duration_months: int | None = None
    label: str | None = None
    email: str | None = None
    features: list[str] | None = None


class PlanInvitationRedeemResponse(BaseModel):
    status: str
    message: str | None = None
    plan: str | None = None
    plan_expires_at: datetime | None = None
