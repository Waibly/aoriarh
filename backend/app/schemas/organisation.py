import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr


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
