"""Admin dashboard: single endpoint aggregating system health metrics."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.api_usage import ApiUsageLog
from app.models.document import Document
from app.models.organisation import Organisation
from app.models.sync_log import SyncLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class DashboardStats(BaseModel):
    # Users & orgs
    total_users: int
    active_users: int
    total_organisations: int

    # Documents
    total_documents: int
    indexed_documents: int
    pending_documents: int
    error_documents: int
    bocc_reserve: int
    total_chunks: int

    # Usage (last 7 days)
    questions_7d: int
    questions_today: int
    ingestions_7d: int
    cost_7d: float

    # Usage (last 30 days)
    questions_30d: int
    cost_30d: float

    # Syncs
    last_sync_type: str | None
    last_sync_status: str | None
    last_sync_at: str | None
    failed_syncs_24h: int

    # LLM model
    current_model: str


@router.get("/", response_model=DashboardStats)
async def get_dashboard(
    _user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    """Single endpoint returning all admin dashboard metrics."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    twenty_four_hours_ago = now - timedelta(hours=24)

    # --- Users & orgs ---
    users_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(User.is_active.is_(True)).label("active"),
        ).select_from(User)
    )
    users_row = users_q.one()

    orgs_count = await db.execute(select(func.count()).select_from(Organisation))
    total_orgs = orgs_count.scalar() or 0

    # --- Documents ---
    # Exclude BOCC reserve docs (pending but stored intentionally until CCN installed)
    bocc_reserve_filter = ~(
        Document.organisation_id.is_(None)
        & Document.storage_path.ilike("common/ccn/%/bocc_%")
        & (Document.indexation_status == "pending")
    )
    docs_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Document.indexation_status == "indexed").label("indexed"),
            func.count().filter(
                (Document.indexation_status == "pending") & bocc_reserve_filter
            ).label("pending"),
            func.count().filter(Document.indexation_status == "error").label("error"),
            func.coalesce(func.sum(Document.chunk_count), 0).label("chunks"),
        ).select_from(Document)
    )
    docs_row = docs_q.one()

    # Count BOCC reserve separately
    bocc_reserve_q = await db.execute(
        select(func.count()).select_from(Document).where(
            Document.organisation_id.is_(None),
            Document.storage_path.ilike("common/ccn/%/bocc_%"),
            Document.indexation_status == "pending",
        )
    )
    bocc_reserve = bocc_reserve_q.scalar() or 0

    # --- Usage 7 days ---
    usage_7d = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "ingestion"
            ).label("ingestions"),
            func.coalesce(func.sum(ApiUsageLog.cost_usd), 0).label("cost"),
        ).where(ApiUsageLog.created_at >= seven_days_ago)
    )
    usage_7d_row = usage_7d.one()

    # --- Usage today ---
    usage_today = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
        ).where(ApiUsageLog.created_at >= today_start)
    )
    today_row = usage_today.one()

    # --- Usage 30 days ---
    usage_30d = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
            func.coalesce(func.sum(ApiUsageLog.cost_usd), 0).label("cost"),
        ).where(ApiUsageLog.created_at >= thirty_days_ago)
    )
    usage_30d_row = usage_30d.one()

    # --- Last sync ---
    last_sync_q = await db.execute(
        select(SyncLog)
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    )
    last_sync = last_sync_q.scalar_one_or_none()

    # --- Failed syncs 24h ---
    failed_syncs = await db.execute(
        select(func.count()).select_from(SyncLog).where(
            SyncLog.status == "error",
            SyncLog.started_at >= twenty_four_hours_ago,
        )
    )
    failed_24h = failed_syncs.scalar() or 0

    # --- LLM model ---
    import app.rag.config as rag_config
    current_model = rag_config.LLM_MODEL

    return DashboardStats(
        total_users=users_row.total,
        active_users=users_row.active,
        total_organisations=total_orgs,
        total_documents=docs_row.total,
        indexed_documents=docs_row.indexed,
        pending_documents=docs_row.pending,
        error_documents=docs_row.error,
        bocc_reserve=bocc_reserve,
        total_chunks=docs_row.chunks,
        questions_7d=usage_7d_row.questions,
        questions_today=today_row.questions,
        ingestions_7d=usage_7d_row.ingestions,
        cost_7d=float(usage_7d_row.cost),
        questions_30d=usage_30d_row.questions,
        cost_30d=float(usage_30d_row.cost),
        last_sync_type=last_sync.sync_type if last_sync else None,
        last_sync_status=last_sync.status if last_sync else None,
        last_sync_at=last_sync.started_at.isoformat() if last_sync else None,
        failed_syncs_24h=failed_24h,
        current_model=current_model,
    )
