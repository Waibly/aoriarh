import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, model_validator


class FormeJuridique(StrEnum):
    SAS = "SAS"
    SARL = "SARL"
    SA = "SA"
    SASU = "SASU"
    EURL = "EURL"
    SCI = "SCI"
    SNC = "SNC"
    ASSOCIATION = "Association loi 1901"
    AUTO_ENTREPRENEUR = "Auto-entrepreneur/Micro-entreprise"
    SCOP = "SCOP"
    GIE = "GIE"


class Taille(StrEnum):
    XS = "1-10"
    S = "11-50"
    M = "51-250"
    L = "251-500"
    XL = "501-1000"
    XXL = "1000+"


class PlanType(StrEnum):
    GRATUIT = "gratuit"
    INVITE = "invite"
    VIP = "vip"


class RoleInOrg(StrEnum):
    MANAGER = "manager"
    USER = "user"


class OrganisationCreate(BaseModel):
    name: str
    forme_juridique: FormeJuridique | None = None
    taille: Taille | None = None


class OrganisationRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    forme_juridique: str | None
    taille: str | None
    account_id: uuid.UUID | None = None
    created_at: datetime


class OrganisationUpdate(BaseModel):
    name: str | None = None
    forme_juridique: FormeJuridique | None = None
    taille: Taille | None = None


class MembershipRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: uuid.UUID
    organisation_id: uuid.UUID
    role_in_org: str
    created_at: datetime
    user_email: str | None = None
    user_full_name: str | None = None


class MembershipCreate(BaseModel):
    email: EmailStr
    role_in_org: RoleInOrg = RoleInOrg.USER


class MembershipUpdate(BaseModel):
    role_in_org: RoleInOrg


class PlanAssign(BaseModel):
    plan: PlanType
    duration_months: int | None = None

    @model_validator(mode="after")
    def validate_duration(self) -> "PlanAssign":
        if self.plan == PlanType.INVITE:
            if self.duration_months not in (1, 2, 3):
                raise ValueError("duration_months doit être 1, 2 ou 3 pour le plan invité")
        else:
            self.duration_months = None
        return self
