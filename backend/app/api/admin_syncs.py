"""Admin endpoints for sync monitoring and manual triggers."""

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.sync_log import SyncLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class SyncLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    sync_type: str
    idcc: str | None
    status: str
    items_fetched: int
    items_created: int
    items_updated: int
    items_skipped: int
    errors: int
    error_message: str | None
    duration_ms: int | None
    started_at: str
    completed_at: str | None


class SyncLogsResponse(BaseModel):
    logs: list[SyncLogRead]
    total: int


@router.get("/logs", response_model=SyncLogsResponse)
async def list_sync_logs(
    sync_type: str | None = Query(None, description="Filter by type: jurisprudence, ccn"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> SyncLogsResponse:
    """List sync logs with optional filtering."""
    query = select(SyncLog).order_by(desc(SyncLog.started_at))
    count_query = select(SyncLog)

    if sync_type:
        query = query.where(SyncLog.sync_type == sync_type)
        count_query = count_query.where(SyncLog.sync_type == sync_type)

    # Count
    from sqlalchemy import func
    total_result = await db.execute(
        select(func.count()).select_from(count_query.subquery())
    )
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = result.scalars().all()

    return SyncLogsResponse(
        logs=[
            SyncLogRead(
                id=str(log.id),
                sync_type=log.sync_type,
                idcc=log.idcc,
                status=log.status,
                items_fetched=log.items_fetched,
                items_created=log.items_created,
                items_updated=log.items_updated,
                items_skipped=log.items_skipped,
                errors=log.errors,
                error_message=log.error_message,
                duration_ms=log.duration_ms,
                started_at=log.started_at.isoformat(),
                completed_at=log.completed_at.isoformat() if log.completed_at else None,
            )
            for log in logs
        ],
        total=total,
    )


@router.post("/trigger")
async def trigger_scheduled_sync(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger the bi-monthly sync (jurisprudence + CCN rotation)."""
    running = await db.execute(
        select(SyncLog).where(
            SyncLog.sync_type.in_(["jurisprudence", "ccn"]),
            SyncLog.status == "running",
        )
    )
    if running.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Une synchronisation est déjà en cours")

    from app.rag.tasks import enqueue_scheduled_sync
    await enqueue_scheduled_sync()
    return {"detail": "Synchronisation planifiée lancée"}


@router.post("/bocc")
async def trigger_bocc_sync(
    user: User = Depends(require_role(["admin"])),
    year: int | None = Query(None),
    week: int | None = Query(None),
) -> dict:
    """Manually trigger BOCC sync. If year/week omitted, syncs latest available."""
    from app.rag.tasks import enqueue_bocc_sync
    await enqueue_bocc_sync(str(user.id), year=year, week=week)
    label = f"{year}-{week:02d}" if year and week else "dernier disponible"
    return {"detail": f"Synchronisation BOCC lancée ({label})"}


@router.post("/bocc/backfill")
async def trigger_bocc_backfill(
    user: User = Depends(require_role(["admin"])),
) -> dict:
    """Launch full BOCC backfill (3 last years)."""
    from app.rag.tasks import enqueue_bocc_backfill
    await enqueue_bocc_backfill(str(user.id))
    return {"detail": "Backfill BOCC lancé (2023-2025). Opération longue, voir les logs."}


@router.post("/code-travail")
async def trigger_code_travail_sync(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger Code du travail sync from Légifrance API."""
    # Check if a sync is already running (document pending/indexing for code_travail)
    from sqlalchemy import or_
    running = await db.execute(
        select(SyncLog).where(
            SyncLog.sync_type == "code_travail",
            SyncLog.status == "running",
        )
    )
    if running.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Une synchronisation du Code du travail est déjà en cours")

    from app.rag.tasks import enqueue_code_travail_sync
    await enqueue_code_travail_sync(str(user.id))
    return {"detail": "Synchronisation du Code du travail lancée"}
