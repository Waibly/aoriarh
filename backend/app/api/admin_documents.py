import logging
import urllib.parse
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.document import Document
from app.models.user import User
from app.rag.tasks import enqueue_ingestion
from app.schemas.document import (
    AdminDocumentRead,
    BatchUploadFileResult,
    BatchUploadResponse,
    DocumentDownload,
    DocumentRead,
)
from app.services.audit_service import log_admin_action
from app.services.document_service import MAX_FILE_SIZE_ADMIN, DocumentService

logger = logging.getLogger(__name__)

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


MAX_FILES_PER_BATCH = 20


@router.post("/batch", response_model=BatchUploadResponse)
async def upload_common_documents_batch(
    request: Request,
    files: list[UploadFile],
    source_type: str = Form(...),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> BatchUploadResponse:
    """Upload multiple common documents of the same type in one request."""
    if len(files) > MAX_FILES_PER_BATCH:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES_PER_BATCH} fichiers par lot",
        )

    # Validate all files first (size, format)
    allowed_types = {
        "application/pdf", "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    for file in files:
        if file.size and file.size > MAX_FILE_SIZE_ADMIN:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Le fichier {file.filename} dépasse la taille maximale",
            )

    service = DocumentService(db)
    results: list[BatchUploadFileResult] = []

    for file in files:
        try:
            doc = await service.upload_common_document(
                file=file,
                source_type=source_type,
                user_id=user.id,
                max_file_size=MAX_FILE_SIZE_ADMIN,
            )
            await log_admin_action(
                db,
                user_id=user.id,
                action="upload_common_document",
                resource_type="document",
                resource_id=str(doc.id),
                ip_address=request.client.host if request.client else None,
                details=f"file={file.filename} source_type={source_type} batch=true",
            )
            await db.commit()
            await enqueue_ingestion(str(doc.id))
            results.append(BatchUploadFileResult(
                filename=file.filename or "unknown",
                success=True,
                document=DocumentRead.model_validate(doc),
            ))
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            logger.warning("Batch upload failed for %s: %s", file.filename, detail)
            results.append(BatchUploadFileResult(
                filename=file.filename or "unknown",
                success=False,
                error=detail,
            ))

    succeeded = sum(1 for r in results if r.success)
    return BatchUploadResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@router.get("/", response_model=list[DocumentRead])
async def list_common_documents(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    service = DocumentService(db)
    return await service.list_common_documents()  # type: ignore[return-value]


class DocumentGroupItem(BaseModel):
    """A group of common documents by source_type."""
    source_type: str
    label: str
    count: int
    indexed: int
    pending: int
    total_chunks: int


class DocumentGroupsResponse(BaseModel):
    groups: list[DocumentGroupItem]
    total: int


@router.get("/groups", response_model=DocumentGroupsResponse)
async def list_common_document_groups(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentGroupsResponse:
    """Return common documents grouped by source_type with counts."""
    from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY

    result = await db.execute(
        select(
            Document.source_type,
            func.count().label("count"),
            func.count().filter(Document.indexation_status == "indexed").label("indexed"),
            func.count().filter(Document.indexation_status == "pending").label("pending"),
            func.coalesce(func.sum(Document.chunk_count), 0).label("total_chunks"),
        )
        .where(Document.organisation_id.is_(None))
        .group_by(Document.source_type)
        .order_by(func.count().desc())
    )
    rows = result.all()

    source_labels = {
        "code_travail": "Code du travail (législatif)",
        "code_travail_reglementaire": "Code du travail (réglementaire)",
        "arret_cour_cassation": "Jurisprudence — Cour de cassation",
        "convention_collective_nationale": "Conventions collectives & BOCC",
        "constitution": "Constitution",
        "convention_oit": "Conventions OIT",
        "code_civil": "Code civil",
        "code_penal": "Code pénal",
    }

    groups = []
    total = 0
    for row in rows:
        label = source_labels.get(row.source_type, row.source_type)
        groups.append(DocumentGroupItem(
            source_type=row.source_type,
            label=label,
            count=row.count,
            indexed=row.indexed,
            pending=row.pending,
            total_chunks=row.total_chunks,
        ))
        total += row.count

    return DocumentGroupsResponse(groups=groups, total=total)


@router.get("/groups/{source_type}", response_model=list[DocumentRead])
async def list_common_documents_by_type(
    source_type: str,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    """Return common documents for a specific source_type with pagination."""
    result = await db.execute(
        select(Document)
        .where(
            Document.organisation_id.is_(None),
            Document.source_type == source_type,
        )
        .order_by(Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all())  # type: ignore[return-value]


@router.get("/{document_id}/download")
async def download_common_document(
    document_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = DocumentService(db)
    doc = await service.get_common_document(document_id)
    from app.services.storage_service import StorageService
    storage = StorageService()
    file_bytes = storage.get_file_bytes(doc.storage_path)

    content_type = "application/octet-stream"
    if doc.file_format == "pdf":
        content_type = "application/pdf"
    elif doc.file_format == "docx":
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif doc.file_format == "txt":
        content_type = "text/plain"

    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(doc.name, safe=""),
        },
    )


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
