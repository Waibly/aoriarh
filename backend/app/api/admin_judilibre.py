"""Admin endpoints for Judilibre synchronization."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.document import Document
from app.models.user import User
from app.rag.tasks import enqueue_judilibre_sync
from app.schemas.document import DocumentRead
from app.services.judilibre_service import JudilibreService, SyncResult

router = APIRouter()


class SyncRequest(BaseModel):
    date_start: date | None = None
    date_end: date | None = None
    chamber: str = "soc"
    publication: str = "b"
    max_decisions: int | None = None


class SyncResponse(BaseModel):
    status: str
    message: str


class JurisprudenceStats(BaseModel):
    total: int
    indexed: int
    pending: int
    indexing: int
    errors: int
    oldest_decision: str | None
    newest_decision: str | None
    last_sync: str | None


@router.get("/stats", response_model=JurisprudenceStats)
async def get_jurisprudence_stats(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JurisprudenceStats:
    """Get statistics about ingested jurisprudence."""
    service = JudilibreService()
    stats = await service.get_stats(db)
    return JurisprudenceStats(**stats)


@router.post("/sync", response_model=SyncResponse)
async def sync_judilibre(
    body: SyncRequest,
    user: User = Depends(require_role(["admin"])),
) -> SyncResponse:
    """Enqueue a Judilibre synchronization job to the background worker.

    The sync runs asynchronously — check the stats endpoint to follow progress.
    """
    await enqueue_judilibre_sync(
        user_id=str(user.id),
        date_start=body.date_start.isoformat() if body.date_start else None,
        date_end=body.date_end.isoformat() if body.date_end else None,
        chamber=body.chamber,
        publication=body.publication,
        max_decisions=body.max_decisions,
    )
    return SyncResponse(
        status="queued",
        message="Synchronisation lancée en arrière-plan. Consultez les statistiques pour suivre la progression.",
    )


@router.get("/decisions", response_model=list[DocumentRead])
async def list_jurisprudence(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> list[DocumentRead]:
    """List ingested jurisprudence decisions (paginated, 1-based)."""
    juris_types = [
        "arret_cour_cassation",
        "arret_conseil_etat",
        "decision_conseil_constitutionnel",
    ]
    result = await db.execute(
        select(Document)
        .where(
            Document.source_type.in_(juris_types),
            Document.organisation_id.is_(None),
        )
        .order_by(Document.date_decision.desc().nullslast(), Document.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all())  # type: ignore[return-value]
