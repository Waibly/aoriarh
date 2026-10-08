"""Personal named dossiers; shared case editing and chat remain in existing services."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.models.case_file import CaseDocumentLink, CaseEntry, CaseEvent, CaseFile
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.dossier import Dossier
from app.services.case_file_service import CASE_FILE_LOAD_OPTIONS, CaseFileService
from app.services.conversation_service import ConversationService
from app.services.organisation_context_service import load_organisation_context


class DossierService:
    def __init__(self, db):
        self.db = db

    async def get(self, dossier_id, user, *, write=False):
        query = (
            select(Dossier)
            .where(Dossier.id == dossier_id)
            .execution_options(populate_existing=True)
        )
        if write:
            query = query.with_for_update()
        dossier = (await self.db.execute(query)).scalar_one_or_none()
        if dossier is None or (dossier.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "Dossier non accessible")
        await ConversationService(self.db)._check_membership(dossier.organisation_id, user)
        if write and dossier.archived_at is not None:
            raise HTTPException(409, "Réactivez le dossier avant de le modifier")
        return dossier

    async def delete(self, dossier_id, user, expected_version):
        """Erase the workspace atomically; journal object cleanup before commit."""
        from sqlalchemy import delete, or_

        from app.models.case_file import CaseTask
        from app.models.conversation import Message
        from app.models.document_extraction import DocumentExtraction
        from app.services.document_extraction_service import delete_extraction_artifacts
        from app.services.document_service import DocumentService, storage
        from app.services.storage_operation_service import (
            finish_pending_storage_deletes,
            queue_storage_delete,
        )

        dossier = await self.get(dossier_id, user)
        dossier = (
            await self.db.execute(
                select(Dossier)
                .where(Dossier.id == dossier_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if dossier is None:
            raise HTTPException(404, "Dossier introuvable")
        if dossier.version != expected_version:
            raise HTTPException(409, "Le dossier a changé. Rechargez-le avant de le supprimer.")
        await self.db.execute(
            select(CaseFile.id).where(CaseFile.id == dossier.case_file_id).with_for_update()
        )
        conversation_ids = list(
            (
                await self.db.scalars(
                    select(Conversation.id)
                    .where(Conversation.dossier_id == dossier_id)
                    .with_for_update()
                )
            ).all()
        )
        private_docs = list(
            (
                await self.db.scalars(
                    select(Document)
                    .where(
                        or_(
                            Document.private_dossier_id == dossier_id,
                            Document.private_conversation_id.in_(conversation_ids),
                        )
                    )
                    .order_by(Document.id)
                    .with_for_update()
                )
            ).all()
        )
        document_ids = [doc.id for doc in private_docs]
        await delete_extraction_artifacts(self.db, storage, document_ids)
        for doc in private_docs:
            await queue_storage_delete(self.db, storage, doc.id, doc.storage_path)
        case_ids = list(
            (
                await self.db.scalars(
                    select(CaseFile.id).where(
                        or_(
                            CaseFile.id == dossier.case_file_id,
                            CaseFile.conversation_id.in_(conversation_ids),
                        )
                    )
                )
            ).all()
        )
        for model in (CaseEvent, CaseTask, CaseDocumentLink, CaseEntry):
            await self.db.execute(delete(model).where(model.case_file_id.in_(case_ids)))
        await self.db.execute(
            delete(DocumentExtraction).where(DocumentExtraction.document_id.in_(document_ids))
        )
        await self.db.execute(delete(Document).where(Document.id.in_(document_ids)))
        await self.db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
        await self.db.execute(
            delete(CaseFile).where(CaseFile.conversation_id.in_(conversation_ids))
        )
        await self.db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        await self.db.execute(delete(Dossier).where(Dossier.id == dossier_id))
        await self.db.execute(delete(CaseFile).where(CaseFile.id == dossier.case_file_id))
        await self.db.commit()
        for document_id in document_ids:
            DocumentService._delete_qdrant_chunks(document_id)
        await finish_pending_storage_deletes(self.db, storage)

    async def discard_unlinked_upload(self, document_id, dossier_id):
        """Compensate a failed association without touching any published document."""
        from sqlalchemy import delete

        from app.models.document_extraction import DocumentExtraction
        from app.services.document_extraction_service import delete_extraction_artifacts
        from app.services.document_service import storage
        from app.services.storage_operation_service import (
            finish_pending_storage_deletes,
            queue_storage_delete,
        )

        doc = (
            await self.db.execute(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.private_dossier_id == dossier_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if doc is None:
            return
        linked = (
            await self.db.execute(
                select(CaseDocumentLink.id).where(CaseDocumentLink.document_id == document_id)
            )
        ).first()
        if linked:
            return
        await delete_extraction_artifacts(self.db, storage, [document_id])
        await queue_storage_delete(self.db, storage, document_id, doc.storage_path)
        await self.db.execute(
            delete(DocumentExtraction).where(DocumentExtraction.document_id == document_id)
        )
        await self.db.delete(doc)
        await self.db.commit()
        await finish_pending_storage_deletes(self.db, storage)

    async def conversation_references(self, dossier, references):
        """The current dossier links, not historical message attachments, define shared context."""
        import uuid

        case = await self.case(dossier)
        if any(not link.document_id for link in case.document_links):
            raise HTTPException(409, "Une pièce du dossier n’est plus disponible. "
                                "Retirez-la dans Documents avant de poursuivre.")
        if any(link.document_id and not link.extraction_id for link in case.document_links):
            raise HTTPException(
                409,
                "Un document du dossier n’est pas prêt. "
                "Terminez sa préparation dans Documents avant de poser une question.",
            )
        common = [
            {
                "document_id": str(link.document_id),
                "extraction_id": str(link.extraction_id),
                "name": link.document_name,
                "scope": "dossier",
            }
            for link in case.document_links
            if link.document_id and link.extraction_id
        ]
        # Older messages did not label common references. Retired private documents
        # from this dossier must not be resurrected by their attachment history.
        private_ids = set(
            (
                await self.db.scalars(
                    select(Document.id).where(
                        Document.id.in_([uuid.UUID(str(r["document_id"])) for r in references]),
                        Document.private_dossier_id == dossier.id,
                    )
                )
            ).all()
        )
        explicit = [
            r
            for r in references
            if r.get("scope") != "dossier" and uuid.UUID(str(r["document_id"])) not in private_ids
        ]
        return list({str(r["document_id"]): r for r in [*explicit, *common]}.values())

    async def case(self, dossier):
        return (
            await self.db.execute(
                select(CaseFile)
                .where(CaseFile.id == dossier.case_file_id)
                .options(*CASE_FILE_LOAD_OPTIONS[:3])
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def summary(self, dossier):
        return (await self.summaries([dossier]))[0]

    async def summaries(self, dossiers):
        if not dossiers:
            return []
        conversation_counts = dict(
            (
                await self.db.execute(
                    select(Conversation.dossier_id, func.count())
                    .where(
                        Conversation.dossier_id.in_([d.id for d in dossiers]),
                        Conversation.hidden_at.is_(None),
                    )
                    .group_by(Conversation.dossier_id)
                )
            ).all()
        )
        document_counts = dict(
            (
                await self.db.execute(
                    select(CaseDocumentLink.case_file_id, func.count())
                    .where(CaseDocumentLink.case_file_id.in_([d.case_file_id for d in dossiers]))
                    .group_by(CaseDocumentLink.case_file_id)
                )
            ).all()
        )
        return [
            {
                "id": dossier.id,
                "organisation_id": dossier.organisation_id,
                "name": dossier.name,
                "description": dossier.description,
                "instructions": dossier.instructions,
                "pinned": dossier.pinned,
                "archived_at": dossier.archived_at,
                "version": dossier.version,
                "created_at": dossier.created_at,
                "updated_at": dossier.updated_at,
                "conversation_count": conversation_counts.get(dossier.id, 0),
                "document_count": document_counts.get(dossier.case_file_id, 0),
            }
            for dossier in dossiers
        ]

    async def detail(self, dossier, *, offset=0, q=""):
        context = await load_organisation_context(self.db, dossier.organisation_id)
        case = await self.case(dossier)
        conversations = list(
            (
                await self.db.execute(
                    select(Conversation)
                    .where(
                        Conversation.dossier_id == dossier.id,
                        Conversation.hidden_at.is_(None),
                        func.coalesce(Conversation.title, "Nouvelle conversation").icontains(
                            q, autoescape=True
                        )
                        if q
                        else True,
                    )
                    .order_by(Conversation.updated_at.desc(), Conversation.id)
                    .offset(offset)
                    .limit(51)
                )
            ).scalars()
        )
        from app.schemas.case_file import CaseFileRead
        from app.schemas.conversation import ConversationRead

        documents = []
        linked_documents = {
            doc.id: doc
            for doc in (
                await self.db.execute(
                    select(Document).where(
                        Document.id.in_(
                            [link.document_id for link in case.document_links if link.document_id]
                        )
                    )
                )
            ).scalars()
        }
        from app.models.document_extraction import DocumentExtraction
        from app.services.conversation_document_service import attachment_readiness

        extractions = {
            row.id: row
            for row in (
                await self.db.scalars(
                    select(DocumentExtraction).where(
                        DocumentExtraction.id.in_(
                            [
                                link.extraction_id
                                for link in case.document_links
                                if link.extraction_id
                            ]
                        )
                    )
                )
            ).all()
        }
        for link in case.document_links:
            doc = linked_documents.get(link.document_id)
            extraction = extractions.get(link.extraction_id)
            document_status = "unavailable"
            if doc and not doc.retired_at:
                document_status = "error"
                if (
                    extraction
                    and extraction.status == "ready"
                    and extraction.source_sha256 == doc.file_hash
                    and extraction.source_storage_path == doc.storage_path
                ):
                    document_status = attachment_readiness(
                        {
                            "text_bytes": extraction.text_bytes,
                            "indexation_status": doc.indexation_status,
                        }
                    )["processing_status"]
            documents.append(
                {
                    "id": link.id,
                    "document_id": link.document_id,
                    "name": link.document_name,
                    "description": link.description,
                    "extraction_id": link.extraction_id,
                    "scope": "dossier" if doc and doc.private_dossier_id else "entreprise",
                    "file_format": doc.file_format if doc else None,
                    "status": document_status,
                    "created_at": link.created_at,
                }
            )
        return {
            **await self.summary(dossier),
            "documents": documents,
            "case_file": CaseFileRead.model_validate(CaseFileService.public_payload(case, context)),
            "conversations": [ConversationRead.model_validate(c) for c in conversations[:50]],
            "has_more": len(conversations) > 50,
        }

    async def create(self, data, user):
        await ConversationService(self.db)._check_membership(data.organisation_id, user)
        existing = (
            await self.db.execute(select(Dossier).where(Dossier.creation_key == data.creation_key))
        ).scalar_one_or_none()
        if existing:
            if existing.user_id != user.id or existing.organisation_id != data.organisation_id:
                raise HTTPException(409, "Cette opération existe déjà")
            return existing
        conversation = None
        original = None
        if data.conversation_id:
            conversation = await ConversationService(self.db).get_conversation(
                data.conversation_id, user
            )
            if (
                conversation.user_id != user.id
                or conversation.organisation_id != data.organisation_id
            ):
                raise HTTPException(404, "Conversation non accessible")
            # Lock the source to serialize concurrent conversions.
            await self.db.execute(
                select(Conversation.id).where(Conversation.id == conversation.id).with_for_update()
            )
            await self.db.refresh(conversation)
            if conversation.dossier_id:
                existing = await self.get(conversation.dossier_id, user)
                if existing.creation_key == data.creation_key:
                    return existing
                raise HTTPException(409, "Cette conversation appartient déjà à un dossier")
            original, _ = await CaseFileService(self.db).get_case_file(conversation.id, user)
            if data.expected_case_version != original.version:
                raise HTTPException(409, "Le contexte a changé. Rechargez-le.")
            if not set(data.entry_ids) <= {e.id for e in original.entries}:
                raise HTTPException(422, "Information étrangère à la conversation")
            if not set(data.document_ids) <= {d.document_id for d in original.document_links}:
                raise HTTPException(422, "Document étranger à la conversation")
        elif data.entry_ids or data.document_ids:
            raise HTTPException(422, "Une conversation source est requise")
        case = CaseFile(conversation_id=None)
        self.db.add(case)
        await self.db.flush()
        dossier = Dossier(
            organisation_id=data.organisation_id,
            user_id=user.id,
            case_file_id=case.id,
            name=data.name,
            creation_key=data.creation_key,
        )
        self.db.add(dossier)
        await self.db.flush()
        if conversation:
            conversation.dossier_id = dossier.id
            for entry in original.entries:
                if entry.id in data.entry_ids:
                    values = {
                        col.name: getattr(entry, col.name)
                        for col in CaseEntry.__table__.columns
                        if col.name
                        not in {
                            "id",
                            "case_file_id",
                            "created_at",
                            "updated_at",
                            "supersedes_entry_id",
                        }
                    }
                    self.db.add(CaseEntry(case_file_id=case.id, **values))
            for link in original.document_links:
                if link.document_id in data.document_ids:
                    values = {
                        col.name: getattr(link, col.name)
                        for col in CaseDocumentLink.__table__.columns
                        if col.name not in {"id", "case_file_id", "created_at", "updated_at"}
                    }
                    self.db.add(CaseDocumentLink(case_file_id=case.id, **values))
        self.db.add(
            CaseEvent(
                case_file_id=case.id,
                case_version=1,
                event_type="dossier_created",
                actor_type="user",
                structured_delta={"dossier_id": str(dossier.id)},
            )
        )
        await self.db.commit()
        return dossier

    async def bump_case(self, dossier, version, event_type, delta):
        changed = await self.db.execute(
            update(CaseFile)
            .where(
                CaseFile.id == dossier.case_file_id,
                CaseFile.version == version,
            )
            .values(version=CaseFile.version + 1, updated_at=datetime.now(UTC))
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "Le dossier a été modifié. Rechargez-le.")
        dossier.updated_at = datetime.now(UTC)
        self.db.add(
            CaseEvent(
                case_file_id=dossier.case_file_id,
                case_version=version + 1,
                event_type=event_type,
                actor_type="user",
                structured_delta=delta,
            )
        )

    async def update(self, dossier, data):
        values = data.model_dump(exclude_unset=True, exclude={"expected_version", "archived"})
        if any(v is None for v in values.values()):
            raise HTTPException(422, "Valeur vide non autorisée")
        if dossier.archived_at and (values or data.archived is not False):
            raise HTTPException(409, "Réactivez le dossier avant de le modifier")
        if data.pinned and not dossier.pinned:
            # Serialize pins for this owner using the user row.
            from app.models.user import User

            await self.db.execute(
                select(User.id).where(User.id == dossier.user_id).with_for_update()
            )
            count = (
                await self.db.execute(
                    select(func.count())
                    .select_from(Dossier)
                    .where(
                        Dossier.user_id == dossier.user_id,
                        Dossier.organisation_id == dossier.organisation_id,
                        Dossier.pinned.is_(True),
                        Dossier.archived_at.is_(None),
                    )
                )
            ).scalar_one()
            if count >= 5:
                raise HTTPException(409, "Cinq dossiers épinglés maximum")
        if data.archived is not None:
            values["archived_at"] = datetime.now(UTC) if data.archived else None
            if data.archived:
                values["pinned"] = False
        changed = await self.db.execute(
            update(Dossier)
            .where(Dossier.id == dossier.id, Dossier.version == data.expected_version)
            .values(**values, version=Dossier.version + 1, updated_at=datetime.now(UTC))
        )
        if changed.rowcount != 1:
            raise HTTPException(409, "Le dossier a changé. Rechargez-le avant d’enregistrer.")
        if any(key in values for key in ("name", "description", "instructions")):
            case = await self.case(dossier)
            await self.bump_case(dossier, case.version, "dossier_context_updated", values)
        await self.db.commit()
        await self.db.refresh(dossier)
        return dossier
