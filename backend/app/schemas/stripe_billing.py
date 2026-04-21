from enum import StrEnum

from pydantic import BaseModel, Field


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
