import uuid
from datetime import datetime

from pydantic import BaseModel


class CcnReferenceRead(BaseModel):
    model_config = {"from_attributes": True}

    idcc: str
    titre: str
    titre_court: str | None = None
    etat: str | None = None


class CcnSearchResult(BaseModel):
    results: list[CcnReferenceRead]
    total: int


class OrganisationConventionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    organisation_id: uuid.UUID
    idcc: str
    status: str
    installed_at: datetime | None = None
    last_synced_at: datetime | None = None
    articles_count: int | None = None
    source_date: str | None = None
    error_message: str | None = None
    created_at: datetime
    # Joined CCN reference fields
    titre: str | None = None
    titre_court: str | None = None

    @classmethod
    def from_orm_with_ccn(cls, obj) -> "OrganisationConventionRead":
        return cls(
            id=obj.id,
            organisation_id=obj.organisation_id,
            idcc=obj.idcc,
            status=obj.status,
            installed_at=obj.installed_at,
            last_synced_at=obj.last_synced_at,
            articles_count=obj.articles_count,
            source_date=obj.source_date,
            error_message=obj.error_message,
            created_at=obj.created_at,
            titre=obj.ccn.titre if obj.ccn else None,
            titre_court=obj.ccn.titre_court if obj.ccn else None,
        )


class InstallConventionRequest(BaseModel):
    idcc: str
