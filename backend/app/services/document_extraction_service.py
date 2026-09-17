"""Canonical raw extraction sidecar. No summarization, RAG lookup or LLM call.

Only organisation-owned documents are supported in this first pilot. Common
corpus/CCN access requires its own policy; it is deliberately not broadened here.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.membership import Membership
from app.models.user import User
from app.rag.text_extractor import TextExtractor
from app.services.storage_operation_service import (
    StorageOperationService,
    finish_storage_io,
    queue_storage_delete,
)
from app.services.storage_service import StorageService

MAX_EXTRACTION_BYTES = 10 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024


async def delete_extraction_artifacts(
    db: AsyncSession,
    storage: StorageService,
    document_ids: list[uuid.UUID],
) -> int:
    """Queue physical erasure in the same transaction as authorized logical erasure.

    Caller commits, then calls finish_pending_storage_deletes. Recovery can finish
    a failed DELETE without recreating a deleted document or losing its target.
    """
    if not document_ids:
        return 0
    # Same lock as extraction publication: a deletion cannot miss an artifact
    # that an in-flight worker publishes immediately after the cleanup query.
    locked = await db.execute(
        select(Document)
        .where(Document.id.in_(document_ids))
        .order_by(Document.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Refresh already-loaded parent objects too: a replacement may have committed
    # while deletion waited for its lock. Callers must erase the CURRENT source.
    locked.scalars().all()
    result = await db.execute(
        select(DocumentExtraction.document_id, DocumentExtraction.text_storage_path).where(
            DocumentExtraction.document_id.in_(document_ids),
            DocumentExtraction.text_storage_path.is_not(None),
        )
    )
    paths = result.all()
    for document_id, path in paths:
        await queue_storage_delete(db, storage, document_id, path)
    await db.execute(
        delete(DocumentExtraction).where(DocumentExtraction.document_id.in_(document_ids))
    )
    return len(paths)


class ExtractionError(RuntimeError):
    """Safe machine-readable technical error, never a provider error body."""


@dataclass(frozen=True)
class SourceSnapshot:
    document_id: uuid.UUID
    organisation_id: uuid.UUID
    storage_path: str
    file_hash: str
    name: str
    file_format: str

    @classmethod
    def from_document(cls, doc: Document):
        if doc.organisation_id is None or not doc.file_hash:
            raise ExtractionError("source_version_unavailable")
        return cls(
            doc.id,
            doc.organisation_id,
            doc.storage_path,
            doc.file_hash,
            doc.name,
            doc.file_format or "pdf",
        )


def extractor_version(file_format: str) -> str:
    packages = {"pdf": "pymupdf4llm", "docx": "python-docx"}
    package = packages.get(file_format)
    dependency = version(package) if package else "builtin"
    return f"raw-v1:{file_format}:{dependency}"


def coverage_manifest(file_format: str) -> dict:
    # Capability limitations, not semantic judgments or guessed omissions.
    limitations = {
        "pdf": ["no_ocr", "images_not_transcribed", "layout_completeness_not_certified"],
        "docx": [
            "headers_footers_not_extracted",
            "images_not_transcribed",
            "notes_textboxes_not_certified",
        ],
        "txt": [],
        "md": [],
    }
    return {
        "scope": "raw_extracted_text",
        "file_completeness": "not_certified",
        "limitations": limitations.get(file_format, ["format_coverage_unknown"]),
    }


class DocumentExtractionService:
    def __init__(self, db: AsyncSession, storage: StorageService | None = None):
        self.db = db
        self.storage = storage if storage is not None else StorageService()

    async def _locked_current(self, snapshot: SourceSnapshot) -> None:
        result = await self.db.execute(
            select(Document.organisation_id, Document.storage_path, Document.file_hash)
            .where(Document.id == snapshot.document_id)
            .with_for_update()
        )
        doc = result.first()
        if (
            doc is None
            or doc.organisation_id != snapshot.organisation_id
            or doc.storage_path != snapshot.storage_path
            or doc.file_hash != snapshot.file_hash
        ):
            raise ExtractionError("source_version_changed")

    async def extract(
        self, snapshot: SourceSnapshot, file_bytes: bytes, extractor: TextExtractor
    ) -> str:
        """Serialize attempts on a document; reuse a verified successful artifact.

        Caller owns a dedicated ingestion session. Commit releases the row lock.
        No indexation flag can be interpreted as proof of extraction completeness.
        """
        await self._locked_current(snapshot)
        if hashlib.sha256(file_bytes).hexdigest() != snapshot.file_hash:
            await self.db.rollback()
            raise ExtractionError("source_integrity_error")
        implementation = extractor_version(snapshot.file_format)
        existing = (
            (
                await self.db.execute(
                    select(DocumentExtraction)
                    .where(
                        DocumentExtraction.document_id == snapshot.document_id,
                        DocumentExtraction.source_storage_path == snapshot.storage_path,
                        DocumentExtraction.source_sha256 == snapshot.file_hash,
                        DocumentExtraction.extractor_version == implementation,
                        DocumentExtraction.status == "ready",
                    )
                    .order_by(DocumentExtraction.created_at.desc(), DocumentExtraction.id.desc())
                )
            )
            .scalars()
            .first()
        )
        if existing:
            try:
                text = await self._read_artifact(existing, MAX_EXTRACTION_BYTES)
                await self.db.commit()
                return text
            except Exception:
                await self.db.rollback()
                raise

        record = DocumentExtraction(
            id=uuid.uuid4(),
            document_id=snapshot.document_id,
            source_storage_path=snapshot.storage_path,
            source_sha256=snapshot.file_hash,
            source_name=snapshot.name,
            file_format=snapshot.file_format,
            extractor_version=implementation,
            status="error",
            coverage=coverage_manifest(snapshot.file_format),
            created_at=datetime.now(UTC),
        )
        try:
            text = await asyncio.to_thread(extractor.extract, file_bytes, snapshot.file_format)
        except Exception:
            record.error_code = "extraction_failed"
            self.db.add(record)
            await self.db.commit()
            raise ExtractionError("extraction_failed") from None
        encoded = text.encode("utf-8")
        if not text.strip() or len(encoded) > MAX_EXTRACTION_BYTES:
            record.status = "empty" if not text.strip() else "error"
            record.error_code = "empty_text" if not text.strip() else "extraction_budget_exceeded"
            self.db.add(record)
            await self.db.commit()
            raise ExtractionError(record.error_code)
        path = f"{snapshot.organisation_id}/extractions/{snapshot.document_id}/{record.id}.txt"
        operations = StorageOperationService(self.db, self.storage)
        operation_id = await operations.reserve(snapshot.document_id, path, "extraction")
        # Reservation committed before PUT, so reacquire and revalidate the source.
        await self._locked_current(snapshot)
        operation = await operations.lock_write(operation_id)
        try:
            await finish_storage_io(
                asyncio.to_thread(
                    self.storage.put_file_bytes, path, encoded, "text/plain; charset=utf-8"
                )
            )
        except Exception:
            record.error_code = "extraction_storage_failed"
            operation.status = "delete_pending"
            self.db.add(record)
            await self.db.commit()
            raise ExtractionError("extraction_storage_failed") from None
        record.status = "ready"
        record.text_storage_path = path
        record.text_sha256 = hashlib.sha256(encoded).hexdigest()
        record.text_bytes = len(encoded)
        operation.status = "retained"
        self.db.add(record)
        # Pointer + retained intent commit atomically. If the commit fails, the
        # earlier durable reservation remains eligible for explicit recovery.
        await self.db.commit()
        return text

    async def _authorize(self, doc_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID):
        # Fresh queries even when this session's identity map contains stale objects.
        user = (
            await self.db.execute(
                select(User.id, User.role).where(User.id == user_id, User.is_active.is_(True))
            )
        ).first()
        if not user:
            raise HTTPException(404, "Document non accessible")
        if user.role != "admin":
            member = (
                await self.db.execute(
                    select(Membership.id).where(
                        Membership.user_id == user_id,
                        Membership.organisation_id == org_id,
                        Membership.role_in_org.in_(["manager", "user"]),
                    )
                )
            ).first()
            if member is None:
                raise HTTPException(404, "Document non accessible")
        doc = (
            await self.db.execute(
                select(Document)
                .where(
                    Document.id == doc_id,
                    Document.organisation_id == org_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(404, "Document non accessible")
        return doc

    @staticmethod
    def manifest(record: DocumentExtraction) -> dict:
        return dict(
            extraction_id=record.id,
            document_id=record.document_id,
            source_sha256=record.source_sha256,
            source_name=record.source_name,
            status=record.status,
            error_code=record.error_code,
            extractor_version=record.extractor_version,
            text_bytes=record.text_bytes,
            text_sha256=record.text_sha256,
            coverage=record.coverage,
        )

    async def status(self, doc_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID) -> dict:
        doc = await self._authorize(doc_id, org_id, user_id)
        record = (
            (
                await self.db.execute(
                    select(DocumentExtraction)
                    .where(
                        DocumentExtraction.document_id == doc.id,
                        DocumentExtraction.source_storage_path == doc.storage_path,
                        DocumentExtraction.source_sha256 == doc.file_hash,
                    )
                    .order_by(DocumentExtraction.created_at.desc(), DocumentExtraction.id.desc())
                )
            )
            .scalars()
            .first()
        )
        if record is None:
            return {"document_id": doc.id, "status": "not_available", "extraction_id": None}
        return self.manifest(record)

    async def _read_artifact(self, record: DocumentExtraction, max_bytes: int) -> str:
        if not record.text_storage_path or not record.text_sha256 or record.text_bytes is None:
            raise ExtractionError("extraction_metadata_incomplete")
        if record.text_bytes > max_bytes:
            raise ExtractionError("read_budget_exceeded")
        try:
            data = await asyncio.to_thread(
                self.storage.get_file_bytes_bounded, record.text_storage_path, max_bytes
            )
        except Exception:
            raise ExtractionError("extraction_read_failed") from None
        if len(data) != record.text_bytes or hashlib.sha256(data).hexdigest() != record.text_sha256:
            raise ExtractionError("extraction_integrity_error")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            raise ExtractionError("extraction_encoding_error") from None

    async def read(
        self,
        doc_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        extraction_id: uuid.UUID,
        max_bytes: int,
    ) -> dict:
        if not 1 <= max_bytes <= MAX_READ_BYTES:
            raise HTTPException(422, "Budget de lecture invalide")
        doc = await self._authorize(doc_id, org_id, user_id)
        record = (
            await self.db.execute(
                select(DocumentExtraction).where(
                    DocumentExtraction.id == extraction_id,
                    DocumentExtraction.document_id == doc.id,
                )
            )
        ).scalar_one_or_none()
        if record is None:
            raise HTTPException(404, "Extraction non accessible")
        if record.source_storage_path != doc.storage_path or record.source_sha256 != doc.file_hash:
            raise HTTPException(409, "La version du document a changé")
        if record.status != "ready":
            raise HTTPException(409, "Le texte extrait n'est pas disponible")
        try:
            text = await self._read_artifact(record, max_bytes)
        except ExtractionError as exc:
            if str(exc) == "read_budget_exceeded":
                raise HTTPException(
                    413, "Le texte dépasse le budget de lecture ; aucun texte tronqué"
                )
            raise HTTPException(503, "Erreur technique de lecture de l'extraction") from None
        # A revocation/replacement during object storage I/O must also prevent disclosure.
        doc = await self._authorize(doc_id, org_id, user_id)
        if record.source_storage_path != doc.storage_path or record.source_sha256 != doc.file_hash:
            raise HTTPException(409, "La version du document a changé")
        return {**self.manifest(record), "text": text, "transmitted_scope": "full_extracted_text"}
