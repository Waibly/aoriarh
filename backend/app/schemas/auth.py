from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.stripe_billing import BillingCycle, CommercialPlanCode


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupAttribution(BaseModel):
    """Attribution marketing du premier contact, capturée côté site vitrine.

    Valeurs libres venant de l'URL : on tronque aux tailles des colonnes
    plutôt que de rejeter (une inscription ne doit jamais échouer à cause
    d'un paramètre UTM trop long ou mal formé).
    """

    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None
    gclid: str | None = None
    msclkid: str | None = None
    referrer: str | None = None
    landing_page: str | None = None
    attributed_at: datetime | None = None

    @field_validator(
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "gclid", "msclkid",
    )
    @classmethod
    def _truncate_255(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v[:255] if v else None

    @field_validator("referrer", "landing_page")
    @classmethod
    def _truncate_1024(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v[:1024] if v else None

    def is_empty(self) -> bool:
        return not any(
            getattr(self, f)
            for f in (
                "utm_source", "utm_medium", "utm_campaign", "utm_term",
                "utm_content", "gclid", "msclkid", "referrer", "landing_page",
            )
        )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    workspace_name: str | None = None
    invited: bool = False
    requested_plan: CommercialPlanCode | None = None
    requested_cycle: BillingCycle | None = None
    attribution: SignupAttribution | None = None

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
    attribution: SignupAttribution | None = None
