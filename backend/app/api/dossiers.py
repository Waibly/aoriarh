import asyncio
import logging
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.case_file import CaseDocumentLink, CaseEntry
from app.models.document import Document
from app.models.dossier import Dossier
from app.models.user import User
from app.schemas.case_file import CaseEntryActionRequest
from app.schemas.dossier import DossierCreate, DossierDocumentAction, DossierUpdate, EntryCreate
from app.services.case_file_service import CaseFileService
from app.services.conversation_service import ConversationService
from app.services.dossier_service import DossierService


async def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(private_response)])


@router.get("/{dossier_id}/messages/{message_id}")
async def source_message(
    dossier_id: uuid.UUID,
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.conversation import Conversation, Message

    await DossierService(db).get(dossier_id, user)
    row = (
        await db.execute(
            select(Message.conversation_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Conversation.dossier_id == dossier_id,
                Conversation.hidden_at.is_(None),
            )
        )
    ).first()
    if not row:
        raise HTTPException(404, "Le message source n’est plus disponible")
    return {"conversation_id": row[0]}


@router.post("/{dossier_id}/documents/{document_id}/prepare")
async def prepare_document(
    dossier_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.rag.tasks import enqueue_ingestion
    from app.rag.text_extractor import TextExtractor
    from app.services.document_extraction_service import DocumentExtractionService, SourceSnapshot
    from app.services.storage_service import StorageService

    service = DossierService(db)
    dossier = await service.get(dossier_id, user, write=True)
    link = (
        (
            await db.execute(
                select(CaseDocumentLink).where(
                    CaseDocumentLink.case_file_id == dossier.case_file_id,
                    CaseDocumentLink.document_id == document_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if not link:
        raise HTTPException(404, "Document absent du dossier")
    storage = StorageService()
    reader = DocumentExtractionService(db, storage, dossier_id=dossier_id)
    doc = await reader._authorize(document_id, dossier.organisation_id, user.id)
    raw = await asyncio.to_thread(storage.get_file_bytes, doc.storage_path)
    await reader.extract(SourceSnapshot.from_document(doc), raw, TextExtractor())
    dossier = await service.get(dossier_id, user, write=True)
    link = (
        (
            await db.execute(
                select(CaseDocumentLink)
                .where(
                    CaseDocumentLink.case_file_id == dossier.case_file_id,
                    CaseDocumentLink.document_id == document_id,
                )
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .first()
    )
    if not link:
        raise HTTPException(409, "Le document a été retiré pendant sa préparation.")
    manifest = await reader.status(doc.id, dossier.organisation_id, user.id)
    link.extraction_id = manifest["extraction_id"]
    link.source_sha256 = doc.file_hash
    await service.bump_case(
        dossier,
        (await service.case(dossier)).version,
        "document_prepared",
        {"document_id": str(doc.id)},
    )
    await db.commit()
    await enqueue_ingestion(str(doc.id), expected_source=doc.storage_path)
    return await service.detail(dossier)


@router.get("/")
async def list_dossiers(
    organisation_id: uuid.UUID,
    archived: bool | None = None,
    order: Literal["recent", "pinned"] = "pinned",
    limit: int = Query(50, ge=1, le=50),
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await ConversationService(db)._check_membership(organisation_id, user)
    query = select(Dossier).where(
        Dossier.organisation_id == organisation_id,
        Dossier.user_id == user.id,
    )
    if archived is not None:
        query = query.where(
            Dossier.archived_at.is_not(None) if archived else Dossier.archived_at.is_(None)
        )
    if q:
        from sqlalchemy import or_

        literal = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            or_(
                Dossier.name.ilike(f"%{literal}%", escape="\\"),
                Dossier.description.ilike(f"%{literal}%", escape="\\"),
            )
        )
    rows = list(
        (
            await db.execute(
                query.order_by(
                    *(
                        ([Dossier.pinned.desc()] if order == "pinned" else [])
                        + [Dossier.updated_at.desc(), Dossier.id]
                    )
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).scalars()
    )
    service = DossierService(db)
    return {"items": await service.summaries(rows[:limit]), "has_more": len(rows) > limit}


@router.post("/", status_code=201)
async def create_dossier(
    data: DossierCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    from sqlalchemy.exc import IntegrityError

    service = DossierService(db)
    try:
        dossier = await service.create(data, user)
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(select(Dossier).where(Dossier.creation_key == data.creation_key))
        ).scalar_one_or_none()
        if (
            not existing
            or existing.user_id != user.id
            or existing.organisation_id != data.organisation_id
        ):
            raise HTTPException(409, "Création concurrente : rechargez les dossiers") from None
        dossier = existing
    return await service.detail(dossier)


@router.get("/{dossier_id}")
async def get_dossier(
    dossier_id: uuid.UUID,
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = DossierService(db)
    return await service.detail(await service.get(dossier_id, user), offset=offset, q=q)


@router.delete("/{dossier_id}", status_code=204)
async def delete_dossier(
    dossier_id: uuid.UUID,
    expected_version: int = Query(ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await DossierService(db).delete(dossier_id, user, expected_version)
    return Response(status_code=204)


@router.patch("/{dossier_id}")
async def update_dossier(
    dossier_id: uuid.UUID,
    data: DossierUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = DossierService(db)
    dossier = await service.update(await service.get(dossier_id, user), data)
    return await service.detail(dossier)


@router.post("/{dossier_id}/entries")
async def add_entry(
    dossier_id: uuid.UUID,
    data: EntryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = DossierService(db)
    dossier = await service.get(dossier_id, user, write=True)
    await service.bump_case(
        dossier, data.expected_case_version, "entry_added", {"label": data.label}
    )
    entry_id = uuid.uuid4()
    db.add(
        CaseEntry(
            id=entry_id,
            key=str(entry_id),
            case_file_id=dossier.case_file_id,
            entry_type="fact",
            label=data.label,
            value_text=data.value,
            status="confirmed",
            source_kind="user",
            created_by_user_id=user.id,
        )
    )
    await db.commit()
    return await service.detail(dossier)


@router.post("/{dossier_id}/entries/{entry_id}/revisions")
async def revise_entry(
    dossier_id: uuid.UUID,
    entry_id: uuid.UUID,
    data: CaseEntryActionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = DossierService(db)
    dossier = await service.get(dossier_id, user, write=True)
    await CaseFileService(db).apply_user_entry_action(
        conversation_id=None,
        dossier_id=dossier_id,
        entry_id=entry_id,
        expected_version=data.expected_case_version,
        user=user,
        operation=data.operation,
        value_text=data.value,
        comment=data.comment,
    )
    return await service.detail(dossier)


@router.get("/{dossier_id}/library")
async def library(
    dossier_id: uuid.UUID,
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.conversation_library_service import ConversationLibraryService

    dossier = await DossierService(db).get(dossier_id, user)
    return await ConversationLibraryService(db).search(
        SimpleNamespace(organisation_id=dossier.organisation_id, dossier_id=None),
        name=q,
        offset=offset,
    )


@router.post("/{dossier_id}/documents/actions")
async def document_action(
    dossier_id: uuid.UUID,
    data: DossierDocumentAction,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_access import authorize_private_document

    service = DossierService(db)
    dossier = await service.get(dossier_id, user, write=True)
    if data.operation == "remove" and data.link_id is not None:
        link = (
            await db.execute(
                select(CaseDocumentLink).where(
                    CaseDocumentLink.id == data.link_id,
                    CaseDocumentLink.case_file_id == dossier.case_file_id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            raise HTTPException(404, "Pièce absente du dossier")
        doc = await db.get(Document, link.document_id) if link.document_id else None
        await service.bump_case(
            dossier,
            data.expected_case_version,
            "document_removed",
            {"document_id": str(link.document_id) if link.document_id else None},
        )
        await db.delete(link)
        if doc and doc.private_dossier_id == dossier.id:
            doc.retired_at = datetime.now(UTC)
        await db.commit()
        return await service.detail(dossier)
    if data.document_id is None:
        raise HTTPException(422, "Le document est obligatoire pour cette opération")
    doc = await db.get(Document, data.document_id)
    if not doc or doc.organisation_id != dossier.organisation_id:
        raise HTTPException(404, "Document non accessible")
    await authorize_private_document(db, doc, user, dossier_id=dossier.id)
    links = list(
        (
            await db.execute(
                select(CaseDocumentLink).where(
                    CaseDocumentLink.case_file_id == dossier.case_file_id,
                    CaseDocumentLink.document_id == doc.id,
                )
            )
        ).scalars()
    )
    if data.operation == "attach":
        if links:
            return await service.detail(dossier)
        # Reuse existing extraction and preparation, without a dummy conversation.
        from app.services.conversation_library_service import ConversationLibraryService

        ref = await ConversationLibraryService(db).prepare(
            SimpleNamespace(
                id=None, organisation_id=dossier.organisation_id, dossier_id=dossier.id
            ),
            user,
            doc.id,
            doc.file_hash,
        )
        dossier = await service.get(dossier_id, user, write=True)
        await service.bump_case(
            dossier, data.expected_case_version, "document_attached", {"document_id": str(doc.id)}
        )
        db.add(
            CaseDocumentLink(
                case_file_id=dossier.case_file_id,
                document_id=doc.id,
                extraction_id=ref["extraction_id"],
                document_name=doc.name,
                source_sha256=doc.file_hash,
            )
        )
    else:
        if not links:
            raise HTTPException(404, "Document absent du dossier")
        await service.bump_case(
            dossier,
            data.expected_case_version,
            "document_" + data.operation,
            {"document_id": str(doc.id)},
        )
        if data.operation == "rename":
            if not data.name or not data.name.strip():
                raise HTTPException(422, "Le nom est obligatoire")
            for link in links:
                link.document_name = data.name
                if data.description is not None:
                    link.description = data.description
        else:
            for link in links:
                await db.delete(link)
            if doc.private_dossier_id == dossier.id:
                doc.retired_at = datetime.now(UTC)
    await db.commit()
    return await service.detail(dossier)


@router.post("/{dossier_id}/documents", status_code=201)
async def upload_document(
    dossier_id: uuid.UUID,
    file: UploadFile,
    replace_document_id: uuid.UUID | None = Query(None),
    expected_case_version: int | None = Query(None, ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.organisation import Organisation
    from app.rag.tasks import enqueue_ingestion
    from app.rag.text_extractor import TextExtractor
    from app.services.billing_service import BillingService
    from app.services.document_extraction_service import DocumentExtractionService, SourceSnapshot
    from app.services.document_service import DocumentService, storage

    service = DossierService(db)
    dossier = await service.get(dossier_id, user, write=True)
    previous_links = []
    previous_doc = None
    if replace_document_id:
        if expected_case_version is None:
            raise HTTPException(422, "Version du dossier requise pour un remplacement")
        previous_links = list(
            (
                await db.execute(
                    select(CaseDocumentLink).where(
                        CaseDocumentLink.case_file_id == dossier.case_file_id,
                        CaseDocumentLink.document_id == replace_document_id,
                    )
                )
            ).scalars()
        )
        if not previous_links:
            raise HTTPException(404, "La pièce à remplacer est absente du dossier")
        previous_doc = await db.get(Document, replace_document_id)
    case = await service.case(dossier)
    if expected_case_version is not None and expected_case_version != case.version:
        raise HTTPException(
            409, "Le dossier a été modifié. Rechargez-le avant de remplacer le fichier."
        )
    billing = BillingService(db)
    account = await billing.get_account_for_organisation(dossier.organisation_id)
    billing.ensure_plan_active(account)
    await billing.check_document_limit(await db.get(Organisation, dossier.organisation_id))
    doc = await DocumentService(db).upload_document(
        file,
        "divers",
        dossier.organisation_id,
        user.id,
        private_dossier_id=dossier.id,
        max_file_size=2 * 1024 * 1024,
    )
    uploaded_document_id = doc.id
    try:
        # Recheck after upload, whose storage transaction may release the initial lock.
        dossier = await service.get(dossier_id, user, write=True)
        case = await service.case(dossier)
        await service.bump_case(
            dossier,
            expected_case_version or case.version,
            "document_replaced" if replace_document_id else "document_uploaded",
            {
                "document_id": str(doc.id),
                "replaced_document_id": str(replace_document_id) if replace_document_id else None,
            },
        )
        if replace_document_id == doc.id:
            raise HTTPException(409, "Cette version est déjà présente")
        for previous_link in previous_links:
            await db.delete(previous_link)
        if previous_doc and previous_doc.private_dossier_id == dossier.id:
            previous_doc.retired_at = datetime.now(UTC)

        link = CaseDocumentLink(
            case_file_id=dossier.case_file_id,
            document_id=doc.id,
            document_name=doc.name,
            source_sha256=doc.file_hash,
        )
        db.add(link)
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await service.discard_unlinked_upload(uploaded_document_id, dossier_id)
        except Exception:
            logger.exception("Failed to clean up an unlinked dossier upload")
        raise
    reader = DocumentExtractionService(db, storage, dossier_id=dossier.id)
    try:
        raw = await asyncio.to_thread(storage.get_file_bytes, doc.storage_path)
        await reader.extract(SourceSnapshot.from_document(doc), raw, TextExtractor())
        dossier = await service.get(dossier_id, user, write=True)
        link = (
            (
                await db.execute(
                    select(CaseDocumentLink).where(
                        CaseDocumentLink.case_file_id == dossier.case_file_id,
                        CaseDocumentLink.document_id == uploaded_document_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if link is None:
            raise HTTPException(409, "Le document a été retiré pendant sa préparation.")
        manifest = await reader.status(doc.id, dossier.organisation_id, user.id)
        link.extraction_id = manifest["extraction_id"]
        await db.commit()
        await enqueue_ingestion(str(doc.id), expected_source=doc.storage_path)
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        logger.exception(
            "Dossier document preparation failed",
            extra={"dossier_id": str(dossier_id), "document_id": str(uploaded_document_id)},
        )
        raise HTTPException(
            503,
            "Fichier conservé dans le dossier, mais préparation incomplète. "
            "Réessayez sa préparation.",
        ) from None
    return await service.detail(dossier)


@router.get("/{dossier_id}/documents/{document_id}/download")
async def download(
    dossier_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.document_extraction_service import DocumentExtractionService
    from app.services.storage_service import StorageService

    dossier = await DossierService(db).get(dossier_id, user)
    linked = (
        await db.execute(
            select(CaseDocumentLink.id).where(
                CaseDocumentLink.case_file_id == dossier.case_file_id,
                CaseDocumentLink.document_id == document_id,
            )
        )
    ).first()
    if not linked:
        raise HTTPException(404, "Document absent du dossier")
    doc = await DocumentExtractionService(db, dossier_id=dossier.id)._authorize(
        document_id, dossier.organisation_id, user.id
    )
    raw = await asyncio.to_thread(StorageService().get_file_bytes, doc.storage_path)
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(doc.name, safe=""),
        },
    )
