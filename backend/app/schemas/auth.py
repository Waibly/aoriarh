from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.stripe_billing import BillingCycle, CommercialPlanCode


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    workspace_name: str | None = None
    invited: bool = False
    requested_plan: CommercialPlanCode | None = None
    requested_cycle: BillingCycle | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    checkout_url: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    email: EmailStr
    full_name: str
    google_sub: str
    requested_plan: CommercialPlanCode | None = None
    requested_cycle: BillingCycle | None = None
