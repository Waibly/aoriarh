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
from app.models.conversation import Message
from app.models.document import Document
from app.models.organisation import Organisation
from app.models.sync_log import SyncLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class Incident(BaseModel):
    id: str
    severity: str  # "critical" | "warning" | "info"
    title: str
    detail: str | None = None
    action_label: str
    action_href: str


class QualityHealth(BaseModel):
    feedback_negative_rate_7d: float
    no_sources_rate_7d: float
    out_of_scope_count_7d: int
    latency_p95_ms_7d: float | None


class TimeseriesPoint(BaseModel):
    date: str
    questions: int


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

    # New: RAG quality health
    quality_health: QualityHealth

    # New: incidents
    incidents: list[Incident]

    # New: 30-day questions timeline for the home graph
    questions_timeline_30d: list[TimeseriesPoint]


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
    # cost is filtered on context_type='question' so the home page's
    # "cost / questions" ratio reflects only question-related operations,
    # matching the avg_cost_per_question shown on the costs page.
    usage_7d = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "ingestion"
            ).label("ingestions"),
            func.coalesce(
                func.sum(ApiUsageLog.cost_usd).filter(
                    ApiUsageLog.context_type == "question"
                ),
                0,
            ).label("cost"),
        ).where(
            ApiUsageLog.created_at >= seven_days_ago,
            ApiUsageLog.is_replay.is_(False),
        )
    )
    usage_7d_row = usage_7d.one()

    # --- Usage today ---
    usage_today = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
        ).where(
            ApiUsageLog.created_at >= today_start,
            ApiUsageLog.is_replay.is_(False),
        )
    )
    today_row = usage_today.one()

    # --- Usage 30 days ---
    usage_30d = await db.execute(
        select(
            func.count(func.distinct(ApiUsageLog.context_id)).filter(
                ApiUsageLog.context_type == "question"
            ).label("questions"),
            func.coalesce(
                func.sum(ApiUsageLog.cost_usd).filter(
                    ApiUsageLog.context_type == "question"
                ),
                0,
            ).label("cost"),
        ).where(
            ApiUsageLog.created_at >= thirty_days_ago,
            ApiUsageLog.is_replay.is_(False),
        )
    )
    usage_30d_row = usage_30d.one()

    # --- Last sync ---
    last_sync_q = await db.execute(
        select(SyncLog)
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    )
    last_sync = last_sync_q.scalar_one_or_none()

    # --- Failed syncs 24h (excluding soft errors) ---
    # Soft errors = upstream sources not yet available (DILA delay on
    # BOCC, etc.). They're not real failures, they resolve themselves
    # the next time the cron runs. We exclude them from the dashboard
    # incident count so it doesn't stay red on legitimate situations.
    failed_syncs = await db.execute(
        select(SyncLog).where(
            SyncLog.status == "error",
            SyncLog.started_at >= twenty_four_hours_ago,
        )
    )
    soft_error_patterns = ("introuvable", "not yet available", "not yet published", "404")
    hard_failures = [
        log for log in failed_syncs.scalars().all()
        if not log.error_message
        or not any(p in log.error_message.lower() for p in soft_error_patterns)
    ]
    failed_24h = len(hard_failures)

    # --- LLM model ---
    import app.rag.config as rag_config
    current_model = rag_config.LLM_MODEL

    # --- Quality health (last 7 days) ---
    msgs_q = await db.execute(
        select(Message).where(
            Message.role == "assistant",
            Message.created_at >= seven_days_ago,
        )
    )
    msgs = msgs_q.scalars().all()
    total_msgs = len(msgs)
    if total_msgs > 0:
        # Detect out-of-scope refusals by EITHER flagged trace OR the canned
        # refusal text prefix (catches old messages without persisted trace).
        from app.rag.agent import _OUT_OF_SCOPE_ANSWER
        oos_prefix = _OUT_OF_SCOPE_ANSWER[:60]

        def _is_oos(m) -> bool:
            if m.rag_trace and m.rag_trace.get("out_of_scope") is True:
                return True
            return bool(m.content and m.content.startswith(oos_prefix))

        fb_down = sum(1 for m in msgs if m.feedback == "down")
        oos = sum(1 for m in msgs if _is_oos(m))
        # In-scope questions without any source returned : real warning
        # signal (corpus gap). Out-of-scope refusals are excluded since
        # they legitimately have no sources.
        no_src = sum(
            1 for m in msgs
            if (not m.sources or len(m.sources) == 0) and not _is_oos(m)
        )
        latencies = sorted(m.latency_ms for m in msgs if m.latency_ms is not None)
        if latencies:
            k = (len(latencies) - 1) * 0.95
            f = int(k)
            c = min(f + 1, len(latencies) - 1)
            p95 = float(latencies[f] + (latencies[c] - latencies[f]) * (k - f))
        else:
            p95 = None
        quality_health = QualityHealth(
            feedback_negative_rate_7d=round(fb_down / total_msgs, 4),
            no_sources_rate_7d=round(no_src / total_msgs, 4),
            out_of_scope_count_7d=oos,
            latency_p95_ms_7d=p95,
        )
    else:
        quality_health = QualityHealth(
            feedback_negative_rate_7d=0.0,
            no_sources_rate_7d=0.0,
            out_of_scope_count_7d=0,
            latency_p95_ms_7d=None,
        )

    # --- Incidents (rules-based detection) ---
    incidents: list[Incident] = []
    if docs_row.error > 0:
        incidents.append(Incident(
            id="docs_in_error",
            severity="critical" if docs_row.error >= 5 else "warning",
            title=f"{docs_row.error} document(s) en erreur d'indexation",
            detail="Ces documents ne sont pas interrogeables par le RAG.",
            action_label="Voir les documents",
            action_href="/admin/corpus",
        ))
    if failed_24h > 0:
        incidents.append(Incident(
            id="syncs_failed_24h",
            severity="critical",
            title=f"{failed_24h} synchronisation(s) échouée(s) (24h)",
            detail=(
                f"Dernière sync : {last_sync.sync_type if last_sync else '—'} "
                f"({last_sync.status if last_sync else '—'})"
            ),
            action_label="Voir l'historique",
            action_href="/admin/corpus",
        ))
    if quality_health.feedback_negative_rate_7d > 0.15 and total_msgs >= 10:
        incidents.append(Incident(
            id="feedback_negative_high",
            severity="warning",
            title=f"Taux de feedback négatif élevé ({quality_health.feedback_negative_rate_7d * 100:.0f}%)",
            detail="Certaines réponses dégradent l'expérience utilisateur.",
            action_label="Inspecter",
            action_href="/admin/quality?feedback=down",
        ))
    if (
        quality_health.latency_p95_ms_7d is not None
        and quality_health.latency_p95_ms_7d > 25000
    ):
        # p95 = 95% of requests complete in LESS than this value (not "above"!)
        incidents.append(Incident(
            id="latency_p95_high",
            severity="warning",
            title=(
                f"Temps de réponse trop long sur les cas les plus lents "
                f"({quality_health.latency_p95_ms_7d / 1000:.1f}s)"
            ),
            detail=(
                "Les 5% de questions les plus lentes mettent plus de "
                f"{quality_health.latency_p95_ms_7d / 1000:.0f} secondes à "
                "obtenir une réponse. Cible normale : moins de 20s. "
                "Vérifie les dernières questions pour identifier celles "
                "qui ralentissent le système."
            ),
            action_label="Voir la qualité",
            action_href="/admin/quality",
        ))
    # Sort by severity: critical first
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    incidents.sort(key=lambda i: severity_order.get(i.severity, 99))

    # --- Questions timeline (30 days) ---
    timeline_q = await db.execute(
        select(
            func.date_trunc("day", ApiUsageLog.created_at).label("day"),
            func.count(func.distinct(ApiUsageLog.context_id)).label("count"),
        )
        .where(
            ApiUsageLog.created_at >= thirty_days_ago,
            ApiUsageLog.context_type == "question",
            ApiUsageLog.is_replay.is_(False),
        )
        .group_by("day")
        .order_by("day")
    )
    timeline = [
        TimeseriesPoint(date=row.day.date().isoformat(), questions=int(row.count))
        for row in timeline_q.all()
    ]

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
        quality_health=quality_health,
        incidents=incidents,
        questions_timeline_30d=timeline,
    )
