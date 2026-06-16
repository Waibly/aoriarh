"""Admin business cockpit endpoints.

Reserved for AORIA RH staff (role='admin'). These routes give the company
director a single financial/business view that the existing admin pages never
cross-reference: revenue (billing, EUR) and infra cost (api usage, USD) are
combined into a gross margin, alongside growth, churn-risk and product-value
signals.

Nothing is recomputed from scratch — the aggregations reuse the exact same
sources and predicates as ``admin_billing``, ``admin_costs`` and
``admin_quality`` so the numbers stay consistent across the back-office. Costs
stored in USD are converted to EUR via ``settings.usd_eur_rate``.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.plans import PRICE_MONTHLY_CENTS, PRICE_YEARLY_CENTS
from app.models.account import Account
from app.models.api_usage import ApiUsageLog
from app.models.conversation import Message
from app.models.organisation import Organisation
from app.models.plan_invitation import PlanInvitationRedemption
from app.models.subscription import Subscription
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

_ACTIVE_SUB_STATUSES = ("active", "trialing", "past_due")


def _usd_to_eur(usd: float) -> float:
    return round(usd * settings.usd_eur_rate, 2)


def _mrr_contribution_cents(plan: str, billing_cycle: str) -> int:
    """MRR contribution of a single subscription, normalised to monthly."""
    if billing_cycle == "monthly":
        return PRICE_MONTHLY_CENTS.get(plan, 0)
    return PRICE_YEARLY_CENTS.get(plan, 0) // 12


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AtRiskAccount(BaseModel):
    account_id: str
    account_name: str | None
    owner_email: str | None
    plan: str
    reason: Literal["trial_expiring", "past_due", "inactive"]
    detail: str | None = None


class BusinessOverview(BaseModel):
    # Revenue & profitability
    mrr_eur: float
    arr_eur: float
    subscriptions_by_plan: dict[str, int]
    infra_cost_eur_30d: float
    gross_margin_eur: float
    infra_pct_of_mrr: float | None
    arpu_eur: float | None
    active_subscriptions: int

    # Growth & acquisition
    new_customers_30d: int
    trial_active: int
    trial_to_paid_rate_30d: float | None
    promo_activations_30d: int

    # Risk
    monthly_churn_pct: float
    accounts_past_due: int
    at_risk: list[AtRiskAccount]

    # Product value
    questions_30d: int
    questions_trend_pct: float | None
    satisfaction_rate: float | None
    feedback_negative_rate: float
    no_sources_rate: float


class ClientRow(BaseModel):
    account_id: str
    account_name: str | None
    owner_email: str | None
    plan: str
    status: str
    mrr_eur: float
    questions_30d: int
    infra_cost_eur_30d: float
    margin_eur: float
    last_activity_at: str | None


class ClientsResponse(BaseModel):
    rows: list[ClientRow]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Internal aggregation helpers
# ---------------------------------------------------------------------------


async def _usage_by_account(
    db: AsyncSession, since: datetime
) -> dict[Any, dict[str, Any]]:
    """Per-account usage since ``since``: question count, cost (USD), last activity.

    Joins ApiUsageLog → Organisation → Account via ``Organisation.account_id``.
    Sandbox/replay calls are excluded, matching the cost dashboard.
    """
    stmt = (
        select(
            Organisation.account_id.label("account_id"),
            func.coalesce(func.sum(ApiUsageLog.cost_usd), 0).label("cost_usd"),
            func.count(distinct(ApiUsageLog.context_id))
            .filter(ApiUsageLog.context_type == "question")
            .label("questions"),
            func.max(ApiUsageLog.created_at).label("last_activity"),
        )
        .select_from(ApiUsageLog)
        .join(Organisation, Organisation.id == ApiUsageLog.organisation_id)
        .where(
            ApiUsageLog.is_replay.is_(False),
            ApiUsageLog.created_at >= since,
            Organisation.account_id.isnot(None),
        )
        .group_by(Organisation.account_id)
    )
    rows = (await db.execute(stmt)).all()
    return {
        r.account_id: {
            "cost_usd": float(r.cost_usd or 0.0),
            "questions": int(r.questions or 0),
            "last_activity": r.last_activity,
        }
        for r in rows
    }


async def _mrr_by_account(db: AsyncSession) -> dict[Any, int]:
    """Per-account MRR contribution (cents) from active subscriptions."""
    subs = (
        await db.execute(
            select(Subscription).where(Subscription.status.in_(_ACTIVE_SUB_STATUSES))
        )
    ).scalars()
    out: dict[Any, int] = {}
    for sub in subs:
        out[sub.account_id] = out.get(sub.account_id, 0) + _mrr_contribution_cents(
            sub.plan, sub.billing_cycle
        )
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=BusinessOverview)
async def get_business_overview(
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> BusinessOverview:
    """Single business snapshot: revenue, margin, growth, risk, product value."""
    now = datetime.now(UTC)
    d30 = now - timedelta(days=30)
    d60 = now - timedelta(days=60)

    # --- Revenue (reuses admin_billing logic) ---
    active_subs = list(
        (
            await db.execute(
                select(Subscription).where(
                    Subscription.status.in_(_ACTIVE_SUB_STATUSES)
                )
            )
        ).scalars()
    )
    mrr_cents = 0
    by_plan: dict[str, int] = {"solo": 0, "equipe": 0, "groupe": 0}
    for sub in active_subs:
        by_plan[sub.plan] = by_plan.get(sub.plan, 0) + 1
        mrr_cents += _mrr_contribution_cents(sub.plan, sub.billing_cycle)
    mrr_eur = round(mrr_cents / 100, 2)

    # --- Infra cost over 30d (USD → EUR) ---
    cost_usd_30d = float(
        (
            await db.execute(
                select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
                    ApiUsageLog.is_replay.is_(False),
                    ApiUsageLog.created_at >= d30,
                )
            )
        ).scalar()
        or 0.0
    )
    infra_cost_eur = _usd_to_eur(cost_usd_30d)
    gross_margin_eur = round(mrr_eur - infra_cost_eur, 2)
    infra_pct = round(100 * infra_cost_eur / mrr_eur, 1) if mrr_eur > 0 else None
    arpu_eur = round(mrr_eur / len(active_subs), 2) if active_subs else None

    # --- Growth ---
    new_customers_30d = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.created_at >= d30)
            )
        ).scalar()
        or 0
    )
    trial_active = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.plan == "gratuit", Account.status == "trialing")
            )
        ).scalar()
        or 0
    )
    # Rough funnel snapshot: new paying customers over the open trial pool.
    denom = new_customers_30d + trial_active
    trial_to_paid_rate = round(new_customers_30d / denom, 4) if denom > 0 else None
    promo_activations_30d = int(
        (
            await db.execute(
                select(func.count())
                .select_from(PlanInvitationRedemption)
                .where(PlanInvitationRedemption.redeemed_at >= d30)
            )
        ).scalar()
        or 0
    )

    # --- Risk ---
    canceled_30d = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.status == "canceled",
                    Subscription.canceled_at.isnot(None),
                    Subscription.canceled_at >= d30,
                )
            )
        ).scalar()
        or 0
    )
    monthly_churn_pct = round(100 * canceled_30d / max(1, len(active_subs)), 1)
    accounts_past_due = sum(1 for s in active_subs if s.status == "past_due")
    at_risk = await _build_at_risk(db, now)

    # --- Product value (reuses admin_quality predicates) ---
    qv = await _product_value(db, d30, d60, now)

    return BusinessOverview(
        mrr_eur=mrr_eur,
        arr_eur=round(mrr_eur * 12, 2),
        subscriptions_by_plan=by_plan,
        infra_cost_eur_30d=infra_cost_eur,
        gross_margin_eur=gross_margin_eur,
        infra_pct_of_mrr=infra_pct,
        arpu_eur=arpu_eur,
        active_subscriptions=len(active_subs),
        new_customers_30d=new_customers_30d,
        trial_active=trial_active,
        trial_to_paid_rate_30d=trial_to_paid_rate,
        promo_activations_30d=promo_activations_30d,
        monthly_churn_pct=monthly_churn_pct,
        accounts_past_due=accounts_past_due,
        at_risk=at_risk,
        **qv,
    )


async def _build_at_risk(db: AsyncSession, now: datetime) -> list[AtRiskAccount]:
    """Accounts needing attention: trials expiring <14d, past_due, or dormant."""
    out: list[AtRiskAccount] = []
    in_14d = now + timedelta(days=14)
    d30 = now - timedelta(days=30)

    # Trials expiring within 14 days
    expiring = (
        await db.execute(
            select(Account).where(
                Account.plan.in_(("gratuit", "invite")),
                Account.plan_expires_at.isnot(None),
                Account.plan_expires_at >= now,
                Account.plan_expires_at <= in_14d,
            )
        )
    ).scalars()
    for acc in expiring:
        owner = await db.get(User, acc.owner_id)
        days_left = (acc.plan_expires_at - now).days
        out.append(
            AtRiskAccount(
                account_id=str(acc.id),
                account_name=acc.name,
                owner_email=owner.email if owner else None,
                plan=acc.plan,
                reason="trial_expiring",
                detail=f"Expire dans {days_left} j",
            )
        )

    # Past-due paying accounts
    past_due_subs = (
        await db.execute(
            select(Subscription).where(Subscription.status == "past_due")
        )
    ).scalars()
    for sub in past_due_subs:
        acc = await db.get(Account, sub.account_id)
        owner = await db.get(User, acc.owner_id) if acc else None
        out.append(
            AtRiskAccount(
                account_id=str(sub.account_id),
                account_name=acc.name if acc else None,
                owner_email=owner.email if owner else None,
                plan=sub.plan,
                reason="past_due",
                detail="Paiement en retard",
            )
        )

    # Dormant paying accounts: active commercial plan, 0 question in 30d
    usage = await _usage_by_account(db, d30)
    paying = (
        await db.execute(
            select(Account).where(
                Account.plan.in_(("solo", "equipe", "groupe")),
                Account.status == "active",
            )
        )
    ).scalars()
    for acc in paying:
        if usage.get(acc.id, {}).get("questions", 0) == 0:
            owner = await db.get(User, acc.owner_id)
            out.append(
                AtRiskAccount(
                    account_id=str(acc.id),
                    account_name=acc.name,
                    owner_email=owner.email if owner else None,
                    plan=acc.plan,
                    reason="inactive",
                    detail="0 question sur 30 j",
                )
            )
    return out


async def _product_value(
    db: AsyncSession, d30: datetime, d60: datetime, now: datetime
) -> dict[str, Any]:
    """Satisfaction, negative/no-source rates and question volume + trend.

    Mirrors the predicates in ``admin_quality`` so the cockpit and the quality
    page agree.
    """
    from app.rag.agent import _OUT_OF_SCOPE_ANSWER

    oos_prefix = _OUT_OF_SCOPE_ANSWER[:60]

    rows = (
        await db.execute(
            select(Message).where(
                Message.role == "assistant",
                Message.created_at >= d30,
            )
        )
    ).scalars().all()
    total = len(rows)
    fb_up = sum(1 for m in rows if m.feedback == "up")
    fb_down = sum(1 for m in rows if m.feedback == "down")

    def _is_oos(m: Message) -> bool:
        if m.rag_trace and m.rag_trace.get("out_of_scope") is True:
            return True
        return bool(m.content and m.content.startswith(oos_prefix))

    no_src = sum(
        1 for m in rows if (not m.sources or len(m.sources) == 0) and not _is_oos(m)
    )
    rated = fb_up + fb_down
    satisfaction_rate = round(fb_up / rated, 4) if rated > 0 else None
    feedback_negative_rate = round(fb_down / total, 4) if total > 0 else 0.0
    no_sources_rate = round(no_src / total, 4) if total > 0 else 0.0

    async def _questions(start: datetime, end: datetime) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(distinct(ApiUsageLog.context_id))).where(
                        ApiUsageLog.context_type == "question",
                        ApiUsageLog.is_replay.is_(False),
                        ApiUsageLog.created_at >= start,
                        ApiUsageLog.created_at < end,
                    )
                )
            ).scalar()
            or 0
        )

    q_cur = await _questions(d30, now)
    q_prev = await _questions(d60, d30)
    trend = round(100 * (q_cur - q_prev) / q_prev, 1) if q_prev > 0 else None

    return {
        "questions_30d": q_cur,
        "questions_trend_pct": trend,
        "satisfaction_rate": satisfaction_rate,
        "feedback_negative_rate": feedback_negative_rate,
        "no_sources_rate": no_sources_rate,
    }


@router.get("/clients", response_model=ClientsResponse)
async def get_clients(
    sort: Literal["margin", "mrr", "questions", "activity", "name"] = Query("margin"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> ClientsResponse:
    """Unified per-client view: plan, MRR, usage, infra cost and margin."""
    now = datetime.now(UTC)
    d30 = now - timedelta(days=30)

    accounts = list((await db.execute(select(Account))).scalars())
    usage = await _usage_by_account(db, d30)
    mrr_cents = await _mrr_by_account(db)

    rows: list[ClientRow] = []
    for acc in accounts:
        u = usage.get(acc.id, {})
        cost_eur = _usd_to_eur(u.get("cost_usd", 0.0))
        mrr_eur = round(mrr_cents.get(acc.id, 0) / 100, 2)
        owner = await db.get(User, acc.owner_id)
        last = u.get("last_activity")
        rows.append(
            ClientRow(
                account_id=str(acc.id),
                account_name=acc.name,
                owner_email=owner.email if owner else None,
                plan=acc.plan,
                status=acc.status,
                mrr_eur=mrr_eur,
                questions_30d=u.get("questions", 0),
                infra_cost_eur_30d=cost_eur,
                margin_eur=round(mrr_eur - cost_eur, 2),
                last_activity_at=last.isoformat() if last else None,
            )
        )

    sort_keys = {
        "margin": lambda r: r.margin_eur,
        "mrr": lambda r: r.mrr_eur,
        "questions": lambda r: r.questions_30d,
        "activity": lambda r: r.last_activity_at or "",
        "name": lambda r: (r.account_name or "").lower(),
    }
    reverse = sort != "name"
    rows.sort(key=sort_keys[sort], reverse=reverse)

    total = len(rows)
    start = (page - 1) * page_size
    return ClientsResponse(
        rows=rows[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
    )
