import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.document import Document
from app.models.user import User
from app.rag.tasks import enqueue_ingestion
from app.schemas.document import AdminDocumentRead, DocumentDownload, DocumentRead
from app.services.audit_service import log_admin_action
from app.services.document_service import MAX_FILE_SIZE_ADMIN, DocumentService

router = APIRouter()


class StorageStats(BaseModel):
    total_documents: int
    indexed_count: int
    pending_count: int
    indexing_count: int
    error_count: int
    total_storage_bytes: int
    common_documents: int
    org_documents: int


@router.get("/stats", response_model=StorageStats)
async def get_storage_stats(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> StorageStats:
    s = Document.indexation_status
    result = await db.execute(
        select(
            func.count(Document.id).label("total"),
            func.count(Document.id).filter(s == "indexed").label("indexed"),
            func.count(Document.id).filter(s == "pending").label("pending"),
            func.count(Document.id).filter(s == "indexing").label("indexing"),
            func.count(Document.id).filter(s == "error").label("errors"),
            func.coalesce(func.sum(Document.file_size), 0).label("storage"),
            func.count(Document.id).filter(
                Document.organisation_id.is_(None)
            ).label("common"),
            func.count(Document.id).filter(
                Document.organisation_id.isnot(None)
            ).label("org"),
        )
    )
    row = result.one()
    return StorageStats(
        total_documents=row.total,
        indexed_count=row.indexed,
        pending_count=row.pending,
        indexing_count=row.indexing,
        error_count=row.errors,
        total_storage_bytes=row.storage,
        common_documents=row.common,
        org_documents=row.org,
    )


@router.get("/all", response_model=list[AdminDocumentRead])
async def list_all_documents(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[AdminDocumentRead]:
    """Liste tous les documents (communs + organisations) pour la vue admin."""
    from app.models.organisation import Organisation

    result = await db.execute(
        select(Document, Organisation.name.label("org_name"))
        .outerjoin(Organisation, Document.organisation_id == Organisation.id)
        .order_by(Document.created_at.desc())
    )
    docs = []
    for row in result.all():
        doc = row[0]
        org_name = row[1]
        doc_dict = AdminDocumentRead.model_validate(doc)
        doc_dict.organisation_name = org_name
        docs.append(doc_dict)
    return docs


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_common_document(
    request: Request,
    file: UploadFile,
    source_type: str = Form(...),
    juridiction: str | None = Form(None),
    chambre: str | None = Form(None),
    formation: str | None = Form(None),
    numero_pourvoi: str | None = Form(None),
    date_decision: date | None = Form(None),
    solution: str | None = Form(None),
    publication: str | None = Form(None),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.upload_common_document(
        file=file,
        source_type=source_type,
        user_id=user.id,
        juridiction=juridiction,
        chambre=chambre,
        formation=formation,
        numero_pourvoi=numero_pourvoi,
        date_decision=date_decision,
        solution=solution,
        publication=publication,
        max_file_size=MAX_FILE_SIZE_ADMIN,
    )
    await log_admin_action(
        db,
        user_id=user.id,
        action="upload_common_document",
        resource_type="document",
        resource_id=str(doc.id),
        ip_address=request.client.host if request.client else None,
        details=f"file={file.filename} source_type={source_type}",
    )
    await db.commit()
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]


@router.get("/", response_model=list[DocumentRead])
async def list_common_documents(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    service = DocumentService(db)
    return await service.list_common_documents()  # type: ignore[return-value]


@router.get("/{document_id}/download", response_model=DocumentDownload)
async def download_common_document(
    document_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownload:
    service = DocumentService(db)
    url = await service.get_common_download_url(document_id)
    return DocumentDownload(url=url)


@router.put("/{document_id}", response_model=DocumentRead)
async def replace_common_document(
    request: Request,
    document_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.replace_document(
        doc_id=document_id,
        file=file,
        user_id=user.id,
        org_id=None,
        max_file_size=MAX_FILE_SIZE_ADMIN,
    )
    await log_admin_action(
        db,
        user_id=user.id,
        action="replace_common_document",
        resource_type="document",
        resource_id=str(document_id),
        ip_address=request.client.host if request.client else None,
        details=f"new_file={file.filename}",
    )
    await db.commit()
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_common_document(
    request: Request,
    document_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = DocumentService(db)
    await service.delete_common_document(document_id)
    await log_admin_action(
        db,
        user_id=user.id,
        action="delete_common_document",
        resource_type="document",
        resource_id=str(document_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()


@router.post("/{document_id}/reindex", response_model=DocumentRead)
async def reindex_common_document(
    request: Request,
    document_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.reset_for_reindex(document_id, org_id=None)
    await log_admin_action(
        db,
        user_id=user.id,
        action="reindex_common_document",
        resource_type="document",
        resource_id=str(document_id),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]
