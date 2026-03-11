import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_org_role, require_role
from app.core.limiter import limiter
from app.models.user import User
from app.rag.tasks import enqueue_ingestion
from app.schemas.document import DocumentDownload, DocumentRead
from app.services.document_service import DocumentService

router = APIRouter()


@router.get("/common/", response_model=list[DocumentRead])
async def list_common_documents(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    service = DocumentService(db)
    return await service.list_common_documents()  # type: ignore[return-value]


@router.post(
    "/{organisation_id}/",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/hour")
async def upload_document(
    request: Request,
    organisation_id: uuid.UUID,
    file: UploadFile,
    source_type: str = Form(...),
    juridiction: str | None = Form(None),
    chambre: str | None = Form(None),
    formation: str | None = Form(None),
    numero_pourvoi: str | None = Form(None),
    date_decision: date | None = Form(None),
    solution: str | None = Form(None),
    publication: str | None = Form(None),
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.upload_document(
        file=file,
        source_type=source_type,
        org_id=organisation_id,
        user_id=user.id,
        juridiction=juridiction,
        chambre=chambre,
        formation=formation,
        numero_pourvoi=numero_pourvoi,
        date_decision=date_decision,
        solution=solution,
        publication=publication,
    )
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]


@router.get("/{organisation_id}/", response_model=list[DocumentRead])
async def list_documents(
    organisation_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    service = DocumentService(db)
    docs = await service.list_documents(organisation_id)
    return docs  # type: ignore[return-value]


@router.get("/{organisation_id}/{document_id}", response_model=DocumentRead)
async def get_document(
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.get_document(document_id, organisation_id)
    return doc  # type: ignore[return-value]


@router.get(
    "/{organisation_id}/{document_id}/download",
    response_model=DocumentDownload,
)
async def download_document(
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager", "user"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentDownload:
    service = DocumentService(db)
    url = await service.get_download_url(document_id, organisation_id)
    return DocumentDownload(url=url)


@router.put(
    "/{organisation_id}/{document_id}",
    response_model=DocumentRead,
)
@limiter.limit("30/hour")
async def replace_document(
    request: Request,
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.replace_document(
        doc_id=document_id,
        file=file,
        user_id=user.id,
        org_id=organisation_id,
    )
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]


@router.delete(
    "/{organisation_id}/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = DocumentService(db)
    await service.delete_document(document_id, organisation_id)


@router.post(
    "/{organisation_id}/{document_id}/reindex",
    response_model=DocumentRead,
)
async def reindex_document(
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User = Depends(require_org_role(["manager"])),
    db: AsyncSession = Depends(get_db),
) -> DocumentRead:
    service = DocumentService(db)
    doc = await service.reset_for_reindex(document_id, organisation_id)
    await enqueue_ingestion(str(doc.id))
    return doc  # type: ignore[return-value]
