"""Tenant-scoped metadata search and explicit attachment of existing files.

No embeddings, inferred selection, upload, reindexing or generation processing.
"""

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.membership import Membership
from app.models.user import User
from app.rag.text_extractor import TextExtractor
from app.services.conversation_service import ConversationService
from app.services.document_extraction_service import (
    DocumentExtractionService,
    ExtractionError,
    SourceSnapshot,
)


class ConversationLibraryService:
    def __init__(self, db):
        self.db = db

    async def conversation(self, conversation_id, user):
        conversation = await ConversationService(self.db).get_conversation(conversation_id, user)
        current_user = (
            await self.db.execute(
                select(User.id, User.role).where(
                    User.id == user.id,
                    User.is_active.is_(True),
                )
            )
        ).first()
        if current_user is None:
            raise HTTPException(404, "Conversation non accessible")
        if current_user.role != "admin":
            member = (
                await self.db.execute(
                    select(Membership.id).where(
                        Membership.user_id == user.id,
                        Membership.organisation_id == conversation.organisation_id,
                        Membership.role_in_org.in_(["manager", "user"]),
                    )
                )
            ).first()
            if member is None:
                raise HTTPException(404, "Conversation non accessible")
        if not settings.document_extraction_enabled_for(conversation.organisation_id):
            raise HTTPException(409, "Les pièces jointes ne sont pas activées")
        return conversation

    async def search(
        self, conversation, *, name="", uploaded_from=None, uploaded_to=None, offset=0, limit=20
    ):
        if uploaded_from and uploaded_to and uploaded_from > uploaded_to:
            raise HTTPException(422, "La date de début doit précéder la date de fin")
        query = select(Document).where(Document.organisation_id == conversation.organisation_id)
        if name:
            # Literal filename substring, not SQL wildcard syntax or semantic scoring.
            literal = name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Document.name.ilike(f"%{literal}%", escape="\\"))
        if uploaded_from:
            query = query.where(
                Document.created_at >= datetime.combine(uploaded_from, time.min, UTC)
            )
        if uploaded_to:
            if uploaded_to == date.max:
                raise HTTPException(422, "Date de fin hors limites")
            query = query.where(
                Document.created_at
                < datetime.combine(
                    uploaded_to + timedelta(days=1),
                    time.min,
                    UTC,
                )
            )
        rows = list(
            (
                await self.db.execute(
                    query.order_by(
                        Document.created_at.desc(),
                        Document.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).scalars()
        )
        return {
            "items": [
                {
                    "document_id": d.id,
                    "name": d.name,
                    "source_type": d.source_type,
                    "uploaded_at": d.created_at,
                    "updated_at": d.updated_at,
                    "file_format": d.file_format,
                    "file_size": d.file_size,
                    "source_sha256": d.file_hash,
                }
                for d in rows[:limit]
            ],
            "has_more": len(rows) > limit,
        }

    async def prepare(self, conversation, user, document_id: uuid.UUID, source_sha256: str):
        reader = DocumentExtractionService(self.db)
        doc = await reader._authorize(document_id, conversation.organisation_id, user.id)
        if doc.file_hash != source_sha256:
            raise HTTPException(409, "Le document a changé ; relancez la recherche")
        snapshot = SourceSnapshot.from_document(doc)
        manifest = await reader.status(doc.id, conversation.organisation_id, user.id)
        if manifest["status"] == "not_available":
            # Only prepare legacy files without an extraction. Never repair/retry a
            # failed extraction or replace a corrupt artifact silently.
            if doc.file_format not in {"pdf", "docx", "txt"}:
                raise HTTPException(422, "Format non pris en charge pour la lecture")
            if doc.file_size and doc.file_size > 10 * 1024 * 1024:
                raise HTTPException(
                    413, "Fichier trop volumineux pour la préparation (10 Mo maximum)"
                )
            try:
                raw = await asyncio.to_thread(
                    reader.storage.get_file_bytes_bounded,
                    snapshot.storage_path,
                    10 * 1024 * 1024,
                )
                await reader.extract(snapshot, raw, TextExtractor())
            except ExtractionError as exc:
                if str(exc) == "source_version_changed":
                    raise HTTPException(
                        409, "Le document a changé ; relancez la recherche"
                    ) from None
                raise HTTPException(
                    503, "Préparation du document impossible ; aucune pièce confirmée"
                ) from None
            except Exception:
                raise HTTPException(
                    503, "Lecture du fichier impossible ; aucune pièce confirmée"
                ) from None
            manifest = await reader.status(doc.id, conversation.organisation_id, user.id)
        if manifest["status"] != "ready":
            raise HTTPException(409, "L'extraction de ce document n'est pas disponible")
        if manifest["source_sha256"] != source_sha256:
            raise HTTPException(409, "Le document a changé ; relancez la recherche")
        result = await reader.read(
            doc.id,
            conversation.organisation_id,
            user.id,
            manifest["extraction_id"],
            24_000,
        )
        return {
            "document_id": result["document_id"],
            "extraction_id": result["extraction_id"],
            "name": doc.name,
            "coverage": result["coverage"],
        }
