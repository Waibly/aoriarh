import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def sanitize_indexation_error(self) -> "DocumentRead":
        """Never expose raw technical errors to users."""
        if self.indexation_error:
            self.indexation_error = (
                "L'indexation de ce document a échoué. "
                "Veuillez le réindexer ou contacter le support."
            )
        return self
    uploaded_by: uuid.UUID | None
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


class DocumentListResponse(BaseModel):
    """Réponse paginée + total pour la table admin du corpus."""

    items: list[DocumentRead]
    total: int
    page: int
    page_size: int


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


class ExtractionCoverage(BaseModel):
    scope: Literal["raw_extracted_text"]
    file_completeness: Literal["not_certified"]
    limitations: list[str]


class DocumentExtractionStatus(BaseModel):
    document_id: uuid.UUID
    extraction_id: uuid.UUID | None
    status: Literal["not_available", "ready", "empty", "error"]
    source_sha256: str | None = None
    source_name: str | None = None
    error_code: str | None = None
    extractor_version: str | None = None
    text_bytes: int | None = None
    text_sha256: str | None = None
    coverage: ExtractionCoverage | None = None


class DocumentExtractionText(DocumentExtractionStatus):
    extraction_id: uuid.UUID
    status: Literal["ready"]
    source_sha256: str
    source_name: str
    extractor_version: str
    text_bytes: int
    text_sha256: str
    coverage: ExtractionCoverage
    text: str
    transmitted_scope: Literal["full_extracted_text"]
