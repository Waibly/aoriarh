import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DocumentRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    organisation_id: uuid.UUID | None
    name: str
    source_type: str
    norme_niveau: int | None
    norme_poids: float | None
    indexation_status: str
    indexation_duration_ms: int | None = None
    chunk_count: int | None = None
    indexation_progress: int | None = None
    indexation_error: str | None = None
    uploaded_by: uuid.UUID
    file_size: int | None
    file_format: str | None
    created_at: datetime

    # Métadonnées jurisprudence
    juridiction: str | None = None
    chambre: str | None = None
    formation: str | None = None
    numero_pourvoi: str | None = None
    date_decision: date | None = None
    solution: str | None = None
    publication: str | None = None


class AdminDocumentRead(DocumentRead):
    """DocumentRead enrichi avec le nom de l'organisation pour la vue admin."""

    organisation_name: str | None = None


class BatchUploadFileResult(BaseModel):
    filename: str
    success: bool
    document: DocumentRead | None = None
    error: str | None = None


class BatchUploadResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BatchUploadFileResult]


class DocumentDownload(BaseModel):
    url: str
