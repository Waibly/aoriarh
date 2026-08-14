"""Admin Quality endpoints — KPIs RAG, exploration de conversations, inspection détaillée.

Endpoints:
- GET  /metrics?days=7                  → KPIs agrégés sur la période
- GET  /conversations                   → liste paginée filtrable + recherche full-text
- GET  /messages/{message_id}/inspect   → trace RAG complet d'un message
- POST /sandbox/run                     → exécute une question dans le sandbox (sans persistance)
- POST /sandbox/replay/{message_id}     → rejoue une question existante via le sandbox
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.api_usage import ApiUsageLog
from app.models.ccn import CcnReference, OrganisationConvention
from app.models.conversation import Conversation, Message
from app.models.organisation import Organisation
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ----------------- Schemas -----------------


class KpiTrend(BaseModel):
    current: float
    previous: float
    delta_pct: float | None  # null si previous = 0


class QualityKpis(BaseModel):
    period_days: int
    total_questions: int
    feedback_positive: int
    feedback_negative: int
    feedback_none: int
    feedback_negative_rate: float
    out_of_scope_count: int
    out_of_scope_rate: float
    no_sources_count: int
    no_sources_rate: float
    error_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    latency_p99_ms: float | None
    cost_total_usd: float
    cost_avg_per_question_usd: float | None
    trends: dict[str, KpiTrend]  # negative_rate, latency_p95, cost_avg


class ConversationListItem(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime
    user_email: str | None
    organisation_name: str | None
    question: str
    answer_preview: str
    feedback: str | None
    latency_ms: int | None
    cost_usd: float | None
    has_trace: bool
    is_demo: bool = False  # question posée via la démo publique (org démo)


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    page: int
    page_size: int
    total: int


class OrgCcnInfo(BaseModel):
    idcc: str
    titre: str | None
    status: str  # pending | fetching | indexing | ready | error
    use_custom: bool


class MessageInspect(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    created_at: datetime
    user_email: str | None
    user_profil_metier: str | None
    organisation_name: str | None
    organisation_id: uuid.UUID | None
    org_forme_juridique: str | None
    org_taille: str | None
    org_secteur_activite: str | None
    org_convention_collective: str | None  # libellé brut saisi par l'utilisateur
    org_idccs: list[OrgCcnInfo]  # CCNs effectivement installées
    question: str
    answer: str
    sources: list[dict] | None
    feedback: str | None
    feedback_comment: str | None
    cost_usd: float | None
    latency_ms: int | None
    rag_trace: dict | None


# ----------------- Helpers -----------------


def _source_key(source: dict) -> tuple:
    """Match the production chat's identity key for carried-source deduplication."""
    return (
        source.get("document_id"),
        tuple(sorted(source.get("article_nums") or [])),
        source.get("numero_pourvoi"),
    )


def _get_assistant_with_question_subquery():
    """Build a CTE-style join: assistant message + its preceding user question.

    Strategy: for each assistant message, find the immediately preceding user
    message in the same conversation (ordered by created_at).
    """
    # We use a lateral correlated subquery for the preceding user message.
    return None  # Implemented inline in queries below.


# ----------------- Endpoints -----------------


@router.get("/metrics", response_model=QualityKpis)
async def get_quality_metrics(
    days: int = Query(7, ge=1, le=90),
    account_id: uuid.UUID | None = None,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> QualityKpis:
    """KPIs Qualité agrégés sur la période."""
    now = datetime.now(UTC)
    period_start = now - timedelta(days=days)
    prev_start = now - timedelta(days=days * 2)
    prev_end = period_start

    async def _compute(start: datetime, end: datetime) -> dict:
        """Compute raw aggregates over a period."""
        # Only assistant messages count as "questions answered"
        base_q = select(Message)
        if account_id:
            base_q = (
                base_q.join(Conversation, Message.conversation_id == Conversation.id)
                .join(Organisation, Conversation.organisation_id == Organisation.id)
                .where(Organisation.account_id == account_id)
            )
        base_q = base_q.where(
            Message.role == "assistant",
            Message.created_at >= start,
            Message.created_at < end,
        )
        rows = (await db.execute(base_q)).scalars().all()
        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "fb_up": 0,
                "fb_down": 0,
                "fb_none": 0,
                "oos": 0,
                "no_src": 0,
                "errors": 0,
                "latencies": [],
                "cost_total": 0.0,
                "nb_questions_with_cost": 0,
            }
        fb_up = sum(1 for m in rows if m.feedback == "up")
        fb_down = sum(1 for m in rows if m.feedback == "down")
        fb_none = total - fb_up - fb_down
        # An out-of-scope refusal is detected by EITHER a flagged trace OR
        # the canned refusal text prefix. The text fallback catches old
        # messages from before rag_trace persistence was added, and any
        # future message where the trace failed to write.
        from app.rag.agent import _OUT_OF_SCOPE_ANSWER

        oos_prefix = _OUT_OF_SCOPE_ANSWER[:60]

        def _is_oos(m) -> bool:
            if m.rag_trace and m.rag_trace.get("out_of_scope") is True:
                return True
            return bool(m.content and m.content.startswith(oos_prefix))

        oos = sum(1 for m in rows if _is_oos(m))
        # no_src counts ONLY in-scope questions where the RAG returned no
        # source : that's a real warning signal (corpus gap). Out-of-scope
        # refusals legitimately have no sources and are tracked separately
        # in `oos`, so we exclude them here to avoid inflating the metric.
        no_src = sum(1 for m in rows if (not m.sources or len(m.sources) == 0) and not _is_oos(m))
        errors = sum(1 for m in rows if m.rag_trace and m.rag_trace.get("error"))
        latencies = [m.latency_ms for m in rows if m.latency_ms is not None]
        # Cost is computed live from api_usage_logs (single source of truth,
        # same formula as /admin/costs). Sandbox calls are excluded.
        cost_stmt = select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0))
        if account_id:
            cost_stmt = cost_stmt.join(
                Organisation, Organisation.id == ApiUsageLog.organisation_id
            ).where(Organisation.account_id == account_id)
        cost_q = await db.execute(
            cost_stmt.where(
                ApiUsageLog.context_type == "question",
                ApiUsageLog.is_replay.is_(False),
                ApiUsageLog.created_at >= start,
                ApiUsageLog.created_at < end,
            )
        )
        cost_total = float(cost_q.scalar() or 0.0)
        nbq_stmt = select(func.count(func.distinct(ApiUsageLog.context_id)))
        if account_id:
            nbq_stmt = nbq_stmt.join(
                Organisation, Organisation.id == ApiUsageLog.organisation_id
            ).where(Organisation.account_id == account_id)
        nbq_q = await db.execute(
            nbq_stmt.where(
                ApiUsageLog.context_type == "question",
                ApiUsageLog.is_replay.is_(False),
                ApiUsageLog.created_at >= start,
                ApiUsageLog.created_at < end,
            )
        )
        nb_questions_with_cost = int(nbq_q.scalar() or 0)
        return {
            "total": total,
            "fb_up": fb_up,
            "fb_down": fb_down,
            "fb_none": fb_none,
            "oos": oos,
            "no_src": no_src,
            "errors": errors,
            "latencies": latencies,
            "cost_total": cost_total,
            "nb_questions_with_cost": nb_questions_with_cost,
        }

    cur = await _compute(period_start, now)
    prev = await _compute(prev_start, prev_end)

    def _percentile(values: list[int], pct: float) -> float | None:
        if not values:
            return None
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * (pct / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_vals) - 1)
        if f == c:
            return float(sorted_vals[f])
        return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))

    def _rate(num: int, denom: int) -> float:
        return (num / denom) if denom > 0 else 0.0

    def _trend(cur_val: float, prev_val: float) -> KpiTrend:
        if prev_val == 0:
            return KpiTrend(current=cur_val, previous=prev_val, delta_pct=None)
        delta = ((cur_val - prev_val) / prev_val) * 100.0
        return KpiTrend(current=cur_val, previous=prev_val, delta_pct=round(delta, 1))

    cur_neg_rate = _rate(cur["fb_down"], cur["total"])
    prev_neg_rate = _rate(prev["fb_down"], prev["total"])
    cur_p95 = _percentile(cur["latencies"], 95) or 0.0
    prev_p95 = _percentile(prev["latencies"], 95) or 0.0
    cur_avg_cost = (
        cur["cost_total"] / cur["nb_questions_with_cost"] if cur["nb_questions_with_cost"] else 0.0
    )
    prev_avg_cost = (
        prev["cost_total"] / prev["nb_questions_with_cost"]
        if prev["nb_questions_with_cost"]
        else 0.0
    )

    return QualityKpis(
        period_days=days,
        total_questions=cur["total"],
        feedback_positive=cur["fb_up"],
        feedback_negative=cur["fb_down"],
        feedback_none=cur["fb_none"],
        feedback_negative_rate=round(cur_neg_rate, 4),
        out_of_scope_count=cur["oos"],
        out_of_scope_rate=round(_rate(cur["oos"], cur["total"]), 4),
        no_sources_count=cur["no_src"],
        no_sources_rate=round(_rate(cur["no_src"], cur["total"]), 4),
        error_count=cur["errors"],
        latency_p50_ms=_percentile(cur["latencies"], 50),
        latency_p95_ms=_percentile(cur["latencies"], 95),
        latency_p99_ms=_percentile(cur["latencies"], 99),
        cost_total_usd=round(cur["cost_total"], 4),
        cost_avg_per_question_usd=round(cur_avg_cost, 6) if cur["nb_questions_with_cost"] else None,
        trends={
            "negative_rate": _trend(cur_neg_rate, prev_neg_rate),
            "latency_p95_ms": _trend(cur_p95, prev_p95),
            "cost_avg": _trend(cur_avg_cost, prev_avg_cost),
        },
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    q: str | None = Query(None, description="Recherche full-text français"),
    account_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    feedback: str | None = Query(None, pattern="^(up|down|none|any)$"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    days: int | None = Query(None, ge=1, le=90),
    min_latency_ms: int | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    """Liste paginée des questions assistant avec filtres."""
    # Base : assistant messages join conversation join user join org
    stmt = (
        select(
            Message,
            Conversation,
            User.email.label("user_email"),
            Organisation.name.label("org_name"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .outerjoin(User, Conversation.user_id == User.id)
        .outerjoin(Organisation, Conversation.organisation_id == Organisation.id)
        .where(Message.role == "assistant")
    )

    filters = []
    if account_id:
        filters.append(Organisation.account_id == account_id)
    if organisation_id:
        filters.append(Conversation.organisation_id == organisation_id)
    if user_id:
        filters.append(Conversation.user_id == user_id)
    if date_from:
        filters.append(Message.created_at >= date_from)
    if date_to:
        filters.append(Message.created_at < date_to)
    if days is not None:
        filters.append(Message.created_at >= datetime.now(UTC) - timedelta(days=days))
    if min_latency_ms is not None:
        filters.append(Message.latency_ms >= min_latency_ms)
    if feedback == "up":
        filters.append(Message.feedback == "up")
    elif feedback == "down":
        filters.append(Message.feedback == "down")
    elif feedback == "none":
        filters.append(Message.feedback.is_(None))
    # feedback="any" or None → no filter

    if q:
        # Postgres full-text search en français sur le contenu (utilise le GIN index)
        ts_query = func.plainto_tsquery("french", q)
        ts_vector = func.to_tsvector("french", Message.content)
        filters.append(ts_vector.op("@@")(ts_query))

    if filters:
        stmt = stmt.where(and_(*filters))

    # Total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Page
    stmt = stmt.order_by(Message.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).all()

    # For each assistant message, find the preceding user question (best-effort)
    # and compute the live cost from api_usage_logs.
    items: list[ConversationListItem] = []
    for msg, conv, email, org_name in rows:
        prev_q = await db.execute(
            select(Message.content)
            .where(
                Message.conversation_id == conv.id,
                Message.role == "user",
                Message.created_at <= msg.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        question_text = prev_q.scalar() or ""
        cost_value: float | None = None
        if msg.question_id is not None:
            cost_q = await db.execute(
                select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
                    ApiUsageLog.context_id == msg.question_id,
                    ApiUsageLog.is_replay.is_(False),
                )
            )
            cost_value = float(cost_q.scalar() or 0.0)
        items.append(
            ConversationListItem(
                message_id=msg.id,
                conversation_id=conv.id,
                created_at=msg.created_at,
                user_email=email,
                organisation_name=org_name,
                question=question_text[:300],
                answer_preview=(msg.content or "")[:300],
                feedback=msg.feedback,
                latency_ms=msg.latency_ms,
                cost_usd=cost_value,
                has_trace=msg.rag_trace is not None,
                is_demo=(org_name == settings.demo_org_name),
            )
        )

    return ConversationListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/messages/{message_id}/inspect", response_model=MessageInspect)
async def inspect_message(
    message_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> MessageInspect:
    """Détail complet d'un message assistant pour le drawer d'inspection."""
    stmt = (
        select(
            Message,
            Conversation,
            User.email.label("user_email"),
            User.profil_metier.label("user_profil_metier"),
            Organisation,
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .outerjoin(User, Conversation.user_id == User.id)
        .outerjoin(Organisation, Conversation.organisation_id == Organisation.id)
        .where(Message.id == message_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message non trouvé")
    msg, conv, email, profil_metier, organisation = row
    org_name = organisation.name if organisation else None

    # CCNs installed on the organisation (with their reference titre)
    org_idccs: list[OrgCcnInfo] = []
    if organisation is not None:
        ccns_q = await db.execute(
            select(OrganisationConvention, CcnReference.titre_court, CcnReference.titre)
            .outerjoin(CcnReference, OrganisationConvention.idcc == CcnReference.idcc)
            .where(OrganisationConvention.organisation_id == organisation.id)
            .order_by(OrganisationConvention.idcc)
        )
        for oc, titre_court, titre in ccns_q.all():
            org_idccs.append(
                OrgCcnInfo(
                    idcc=oc.idcc,
                    titre=titre_court or titre,
                    status=oc.status,
                    use_custom=oc.use_custom,
                )
            )

    if msg.role != "assistant":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seuls les messages assistant peuvent être inspectés",
        )

    # Question = previous user message
    prev_q = await db.execute(
        select(Message.content)
        .where(
            Message.conversation_id == conv.id,
            Message.role == "user",
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    question_text = prev_q.scalar() or ""

    cost_value: float | None = None
    if msg.question_id is not None:
        cost_q = await db.execute(
            select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
                ApiUsageLog.context_id == msg.question_id,
                ApiUsageLog.is_replay.is_(False),
            )
        )
        cost_value = float(cost_q.scalar() or 0.0)

    return MessageInspect(
        message_id=msg.id,
        conversation_id=conv.id,
        created_at=msg.created_at,
        user_email=email,
        user_profil_metier=profil_metier,
        organisation_name=org_name,
        organisation_id=organisation.id if organisation else None,
        org_forme_juridique=organisation.forme_juridique if organisation else None,
        org_taille=organisation.taille if organisation else None,
        org_secteur_activite=organisation.secteur_activite if organisation else None,
        org_convention_collective=organisation.convention_collective if organisation else None,
        org_idccs=org_idccs,
        question=question_text,
        answer=msg.content or "",
        sources=msg.sources,
        feedback=msg.feedback,
        feedback_comment=msg.feedback_comment,
        cost_usd=cost_value,
        latency_ms=msg.latency_ms,
        rag_trace=msg.rag_trace,
    )


# ----------------- Sandbox -----------------


class OrganisationItem(BaseModel):
    id: uuid.UUID
    name: str


@router.get("/sandbox/organisations", response_model=list[OrganisationItem])
async def list_organisations_for_sandbox(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[OrganisationItem]:
    """Lightweight org list for the sandbox selector (admin only)."""
    rows = (
        await db.execute(select(Organisation.id, Organisation.name).order_by(Organisation.name))
    ).all()
    return [OrganisationItem(id=r[0], name=r[1]) for r in rows]


class SandboxRunRequest(BaseModel):
    query: str
    organisation_id: uuid.UUID
    history: list[dict] | None = None
    skip_generation: bool = False  # if True, skip the LLM call (retrieval-only)
    search_strategy: Literal["baseline", "adaptive_shadow"] = "baseline"


class SandboxRunResponse(BaseModel):
    answer: str | None
    sources: list[dict]
    rag_trace: dict
    cost_usd: float
    duration_ms: int


async def _run_sandbox_pipeline(
    db: AsyncSession,
    query: str,
    organisation_id: uuid.UUID,
    history: list[dict] | None,
    skip_generation: bool,
    *,
    cited_sources: list[str] | None = None,
    carried_sources: list[dict] | None = None,
    user_profile: str | None = None,
    search_strategy: Literal["baseline", "adaptive_shadow"] = "baseline",
) -> SandboxRunResponse:
    """Execute the RAG pipeline in sandbox mode (no message persistence)."""
    import dataclasses
    import time as _time

    import app.rag.config as rag_config
    from app.models.api_usage import ApiUsageLog as _ApiUsageLog
    from app.rag.agent import RAGAgent
    from app.rag.search_plan import (
        build_deterministic_search_plan,
        run_compact_search_planner,
    )
    from app.services.cost_tracker import compute_cost

    # Verify the organisation exists
    org_q = await db.execute(select(Organisation).where(Organisation.id == organisation_id))
    org = org_q.scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable",
        )

    # Load the same organisation context as the chat endpoint. Installed CCNs
    # are the source of truth; the legacy free-text field is only a fallback.
    ccn_result = await db.execute(
        select(OrganisationConvention.idcc, CcnReference.titre)
        .join(CcnReference, CcnReference.idcc == OrganisationConvention.idcc)
        .where(
            OrganisationConvention.organisation_id == organisation_id,
            OrganisationConvention.status.in_(["ready", "indexing", "fetching"]),
        )
    )
    installed_ccns = ccn_result.all()
    if installed_ccns:
        convention_str = "; ".join(f"{row.titre} (IDCC {row.idcc})" for row in installed_ccns)
    else:
        convention_str = getattr(org, "convention_collective", None)

    not_subject_to_ccn = bool(getattr(org, "not_subject_to_ccn", False))
    idcc_result = await db.execute(
        select(OrganisationConvention.idcc).where(
            OrganisationConvention.organisation_id == organisation_id,
            OrganisationConvention.use_custom.is_(False),
        )
    )
    org_idcc_list = None if not_subject_to_ccn else [r[0] for r in idcc_result.all()] or None

    org_context = {
        "nom": org.name,
        "convention_collective": convention_str,
        "secteur_activite": getattr(org, "secteur_activite", None),
        "forme_juridique": getattr(org, "forme_juridique", None),
        "taille": getattr(org, "taille", None),
        "profil_metier": user_profile,
        "not_subject_to_ccn": not_subject_to_ccn,
    }

    sandbox_id = uuid.uuid4()
    agent = RAGAgent()
    t_start = _time.perf_counter()

    shadow_t0 = _time.perf_counter()
    deterministic_plan = build_deterministic_search_plan(
        query,
        has_history=bool(history),
        org_idcc_list=org_idcc_list,
        not_subject_to_ccn=not_subject_to_ccn,
    )
    planner_result = await run_compact_search_planner(
        deterministic_plan,
        llm=agent.llm,
        model=rag_config.EXPAND_MODEL,
        history=history,
        org_context=org_context,
        timeout_seconds=rag_config.RAG_TIMEOUT_PER_STEP,
    )
    planner_ms = int((_time.perf_counter() - shadow_t0) * 1000)
    planner_cost = float(
        compute_cost(
            "openai",
            rag_config.EXPAND_MODEL,
            planner_result.prompt_tokens,
            planner_result.completion_tokens,
        )
    )
    use_adaptive_plan = search_strategy == "adaptive_shadow" and (
        not deterministic_plan.needs_llm_planner or planner_result.plan.planner_status.value == "ok"
    )

    results, reformulated, rag_trace = await agent.prepare_context(
        query=query,
        organisation_id=str(organisation_id),
        org_context=org_context,
        history=history,
        cited_sources=cited_sources,
        org_idcc_list=org_idcc_list,
        user_id=None,
        conversation_id=str(sandbox_id),
        is_replay=True,
        search_plan=planner_result.plan if use_adaptive_plan else None,
    )

    rag_trace.search_plan = planner_result.plan.to_dict()
    rag_trace.search_plan_usage = {
        "model": rag_config.EXPAND_MODEL,
        "prompt_tokens": planner_result.prompt_tokens,
        "completion_tokens": planner_result.completion_tokens,
        "cost_usd": planner_cost,
        "latency_ms": planner_ms,
        "execution": "adaptive_shadow" if use_adaptive_plan else "observation_only",
        "fallback_to_baseline": (search_strategy == "adaptive_shadow" and not use_adaptive_plan),
    }

    answer: str | None = None
    sources_dicts: list[dict] = []

    if not skip_generation and reformulated != "[HORS_SCOPE]" and results:
        sources = agent.format_sources(results)
        sources_dicts = [dataclasses.asdict(s) for s in sources]
        fresh_keys = {_source_key(source) for source in sources_dicts}
        carried_for_generation = [
            source for source in carried_sources or [] if _source_key(source) not in fresh_keys
        ]
        full_answer = ""
        generate_t0 = _time.perf_counter()
        async for chunk in agent.stream_generate(
            query,
            results,
            org_context=org_context,
            history=history,
            low_confidence=rag_trace.low_confidence,
            condensed_query=reformulated,
            carried_sources=carried_for_generation or None,
            answer_format=(
                planner_result.plan.answer_format if use_adaptive_plan else None
            ),
        ):
            full_answer += chunk
        answer = full_answer
        rag_trace.perf_ms["generate"] = (_time.perf_counter() - generate_t0) * 1000
    elif results:
        sources = agent.format_sources(results)
        sources_dicts = [dataclasses.asdict(s) for s in sources]

    duration_ms = int((_time.perf_counter() - t_start) * 1000)
    rag_trace.perf_ms["total"] = float(duration_ms)

    # Sum costs for this sandbox run
    cost_q = await db.execute(
        select(func.coalesce(func.sum(_ApiUsageLog.cost_usd), 0)).where(
            _ApiUsageLog.context_id == sandbox_id,
        )
    )
    cost_usd = float(cost_q.scalar() or 0.0) + planner_cost

    return SandboxRunResponse(
        answer=answer,
        sources=sources_dicts,
        rag_trace=rag_trace.to_dict(),
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )


@router.post("/sandbox/run", response_model=SandboxRunResponse)
async def sandbox_run(
    body: SandboxRunRequest,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> SandboxRunResponse:
    """Lance une question dans le sandbox sans la persister ni facturer le client."""
    return await _run_sandbox_pipeline(
        db,
        query=body.query,
        organisation_id=body.organisation_id,
        history=body.history,
        skip_generation=body.skip_generation,
        user_profile=user.profil_metier,
        search_strategy=body.search_strategy,
    )


@router.post("/sandbox/replay/{message_id}", response_model=SandboxRunResponse)
async def sandbox_replay(
    message_id: uuid.UUID,
    search_strategy: Literal["baseline", "adaptive_shadow"] = Query("baseline"),
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> SandboxRunResponse:
    """Rejoue une question existante avec le RAG actuel.

    Récupère la question originale + l'historique de la conversation jusqu'à
    ce message, puis exécute en mode sandbox.
    """
    stmt = (
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == message_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message non trouvé")
    msg, conv = row

    # Find the question (previous user message)
    prev_q = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.role == "user",
            Message.created_at <= msg.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    question_message = prev_q.scalar_one_or_none()
    if question_message is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune question utilisateur trouvée pour ce message",
        )
    question_text = question_message.content

    # Production reads the six messages immediately preceding the new question.
    # Fetch newest-first for a correct LIMIT, then restore chronological order.
    hist_q = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.created_at < question_message.created_at,
        )
        .order_by(Message.created_at.desc())
        .limit(6)
    )
    recent_messages = list(reversed(hist_q.scalars().all()))
    history = [{"role": m.role, "content": m.content} for m in recent_messages]

    cited_sources: list[str] = []
    for message in recent_messages:
        if message.role != "assistant" or not message.sources:
            continue
        for source in message.sources:
            if not isinstance(source, dict):
                continue
            name = source.get("document_name")
            if name and name not in cited_sources:
                cited_sources.append(name)

    carried_sources: list[dict] = []
    carried_seen: set[tuple] = set()
    assistant_turns = 0
    for message in reversed(recent_messages):
        if message.role != "assistant" or not message.sources:
            continue
        assistant_turns += 1
        if assistant_turns > 2:
            break
        for source in message.sources:
            if not isinstance(source, dict):
                continue
            key = _source_key(source)
            if key not in carried_seen:
                carried_seen.add(key)
                carried_sources.append(source)

    profile_result = await db.execute(select(User.profil_metier).where(User.id == conv.user_id))
    user_profile = profile_result.scalar_one_or_none()

    return await _run_sandbox_pipeline(
        db,
        query=question_text,
        organisation_id=conv.organisation_id,
        history=history if history else None,
        skip_generation=False,
        cited_sources=cited_sources or None,
        carried_sources=carried_sources or None,
        user_profile=user_profile,
        search_strategy=search_strategy,
    )
