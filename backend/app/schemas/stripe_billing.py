from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class BillingProfile(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    line1: str = Field(min_length=1, max_length=255)
    line2: str = Field(default="", max_length=255)
    postal_code: str = Field(min_length=1, max_length=20)
    city: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    professional: bool = False

    @field_validator("business_name", "line1", "postal_code", "city")
    @classmethod
    def non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Ce champ est obligatoire.")
        return value

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str) -> str:
        return value.upper()


class CommercialPlanCode(StrEnum):
    SOLO = "solo"
    EQUIPE = "equipe"
    GROUPE = "groupe"


class BillingCycle(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class CheckoutRequest(BaseModel):
    plan: CommercialPlanCode = Field(..., description="Commercial plan code to subscribe to")
    cycle: BillingCycle = Field(..., description="Billing cycle (monthly or yearly upfront)")


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalResponse(BaseModel):
    portal_url: str


class BoosterCheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class QuotaResponse(BaseModel):
    """Public quota information exposed to the account owner."""

    plan: str
    status: str
    used: int
    quota: int
    remaining: int
    booster_remaining: int
    period_start: str
    period_end: str
    quota_status: str  # ok | soft_warning | hard_warning
    trial_ends_at: str | None = None


class SubscriptionRead(BaseModel):
    model_config = {"from_attributes": True}

    plan: str
    billing_cycle: str
    status: str
    current_period_end: str | None
    cancel_at_period_end: bool
