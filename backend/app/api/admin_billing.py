"""Admin billing / GDPR endpoints.

These routes are reserved for AORIA RH staff (role='admin') and expose:
  - real-time billing metrics (MRR, ARR, trial pool, churn);
  - a subscription list with filters for the admin UI;
  - a list of accounts currently eligible for (or close to) the scheduled
    GDPR purge, so the team can audit before data is destroyed;
  - an export endpoint returning everything we hold about an account
    (GDPR art. 15 right of access + art. 20 portability);
  - an erasure endpoint that immediately purges an account (GDPR art. 17),
    used to honour user requests without waiting for the daily cron.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.plans import PRICE_MONTHLY_CENTS, PRICE_YEARLY_CENTS
from app.models.account import Account
from app.models.subscription import Subscription
from app.models.user import User
from app.services.data_retention_service import DataRetentionService
from app.services.stripe_service import _get as _stripe_get

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Billing metrics (MRR / ARR / churn / trial pool)
# ---------------------------------------------------------------------------


@router.get("/billing/metrics")
async def get_billing_metrics(
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate billing KPIs for the admin dashboard.

    MRR normalises yearly subscriptions to their monthly equivalent so the
    figure is comparable across mixes of billing cycles.
    """
    now = datetime.now(UTC)
    active_statuses = ("active", "trialing", "past_due")

    subs_result = await db.execute(
        select(Subscription).where(Subscription.status.in_(active_statuses))
    )
    active_subs = list(subs_result.scalars())

    mrr_cents = 0
    by_plan: dict[str, int] = {"solo": 0, "equipe": 0, "groupe": 0}
    for sub in active_subs:
        by_plan[sub.plan] = by_plan.get(sub.plan, 0) + 1
        if sub.billing_cycle == "monthly":
            mrr_cents += PRICE_MONTHLY_CENTS.get(sub.plan, 0)
        else:
            mrr_cents += PRICE_YEARLY_CENTS.get(sub.plan, 0) // 12

    # Trial pool (plan='gratuit' + status='trialing')
    trial_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.plan == "gratuit", Account.status == "trialing")
            )
        ).scalar()
        or 0
    )

    # Suspended accounts (trial expired OR unpaid)
    suspended_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.status == "suspended")
            )
        ).scalar()
        or 0
    )
    canceled_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.status == "canceled")
            )
        ).scalar()
        or 0
    )

    # New subscriptions over the last 30 days (signal of acquisition)
    thirty_days_ago = now - timedelta(days=30)
    new_subs_30d = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.created_at >= thirty_days_ago)
            )
        ).scalar()
        or 0
    )

    # Cancellations over the last 30 days (signal of churn)
    canceled_30d = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.status == "canceled",
                    Subscription.canceled_at.isnot(None),
                    Subscription.canceled_at >= thirty_days_ago,
                )
            )
        ).scalar()
        or 0
    )

    # Monthly churn rate = cancellations / avg active base. We use the current
    # active count as the denominator (good enough at this scale).
    denominator = max(1, len(active_subs))
    monthly_churn_pct = round(100 * canceled_30d / denominator, 1)

    return {
        "mrr_cents": mrr_cents,
        "mrr_eur": round(mrr_cents / 100, 2),
        "arr_cents": mrr_cents * 12,
        "arr_eur": round(mrr_cents * 12 / 100, 2),
        "active_subscriptions": len(active_subs),
        "subscriptions_by_plan": by_plan,
        "trial_active": trial_count,
        "accounts_suspended": suspended_count,
        "accounts_canceled": canceled_count,
        "new_subscriptions_30d": new_subs_30d,
        "cancellations_30d": canceled_30d,
        "monthly_churn_pct": monthly_churn_pct,
    }


# ---------------------------------------------------------------------------
# Subscription list (for admin UI)
# ---------------------------------------------------------------------------


@router.get("/billing/subscriptions")
async def list_subscriptions(
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by subscription status (active, trialing, past_due, canceled, unpaid)",
    ),
    plan: str | None = Query(None, description="Filter by plan (solo, equipe, groupe)"),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return the subscription list with optional filters."""
    stmt = select(Subscription).order_by(Subscription.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter)
    if plan:
        stmt = stmt.where(Subscription.plan == plan)

    result = await db.execute(stmt)
    subs = list(result.scalars())

    rows: list[dict[str, Any]] = []
    for sub in subs:
        account = await db.get(Account, sub.account_id)
        owner = await db.get(User, account.owner_id) if account else None
        mrr_contribution = (
            PRICE_MONTHLY_CENTS.get(sub.plan, 0)
            if sub.billing_cycle == "monthly"
            else PRICE_YEARLY_CENTS.get(sub.plan, 0) // 12
        )
        rows.append(
            {
                "subscription_id": str(sub.id),
                "account_id": str(sub.account_id),
                "account_name": account.name if account else None,
                "owner_email": owner.email if owner else None,
                "plan": sub.plan,
                "billing_cycle": sub.billing_cycle,
                "status": sub.status,
                "current_period_end": sub.current_period_end.isoformat()
                if sub.current_period_end else None,
                "cancel_at_period_end": sub.cancel_at_period_end,
                "canceled_at": sub.canceled_at.isoformat() if sub.canceled_at else None,
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
                "mrr_contribution_cents": mrr_contribution,
            }
        )

    return rows


class CancelSubscriptionRequest(BaseModel):
    at_period_end: bool = True
    """If True (default), schedule cancellation at the end of the current
    billing period — client keeps access until then. If False, cancel
    immediately with no refund."""


@router.post("/billing/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: uuid.UUID,
    body: CancelSubscriptionRequest,
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin-triggered cancellation of a Stripe subscription.

    We delegate the actual cancellation to Stripe. The
    ``customer.subscription.updated`` / ``deleted`` webhook then
    synchronises the local Subscription + Account rows, so we don't
    need to mutate them here manually.
    """
    sub = await db.get(Subscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription non trouvée")
    if not sub.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="Cette subscription n'est pas liée à Stripe (plan technique ?)",
        )
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=501,
            detail="Stripe non configuré côté serveur",
        )

    stripe.api_key = settings.stripe_secret_key
    try:
        if body.at_period_end:
            updated = stripe.Subscription.modify(
                sub.stripe_subscription_id,
                cancel_at_period_end=True,
            )
        else:
            updated = stripe.Subscription.delete(sub.stripe_subscription_id)
    except stripe.error.StripeError as exc:
        logger.exception(
            "Stripe cancellation failed for %s", sub.stripe_subscription_id
        )
        raise HTTPException(status_code=502, detail=f"Erreur Stripe : {exc}") from exc

    # Mirror the cancellation locally right away so the admin UI reflects
    # the new state on the next refetch without waiting for the
    # ``customer.subscription.updated`` webhook round-trip. The webhook
    # will eventually arrive and reconcile if anything drifts.
    account_row = await db.get(Account, sub.account_id)
    if body.at_period_end:
        sub.cancel_at_period_end = True
    else:
        sub.status = "canceled"
        sub.canceled_at = datetime.now(UTC)
        if account_row is not None:
            account_row.status = "canceled"
    await db.commit()

    # Send the cancellation email directly. Mirroring the DB before the
    # webhook means its transition detector would otherwise see
    # (true, true) and skip the email.
    if account_row is not None:
        from app.services.stripe_service import StripeService as _StripeService
        await _StripeService(db)._send_subscription_canceled_email(account_row, sub)

    return {
        "status": _stripe_get(updated, "status", "unknown"),
        "cancel_at_period_end": _stripe_get(updated, "cancel_at_period_end", False),
        "stripe_subscription_id": sub.stripe_subscription_id,
    }


# ---------------------------------------------------------------------------
# Stripe mode (test vs live)
# ---------------------------------------------------------------------------


@router.get("/billing/stripe-status")
async def get_stripe_status(
    _: User = Depends(require_role(["admin"])),
) -> dict[str, Any]:
    """Report whether the backend is wired to Stripe test or live keys.

    Used by the admin UI to show a TEST/LIVE badge so staff never wonder
    which environment the payments are going to. Based on the prefix of
    the configured secret key (Stripe convention: ``sk_test_...`` vs
    ``sk_live_...``). Never returns the key itself.
    """
    key = settings.stripe_secret_key or ""
    if not key:
        return {"configured": False, "mode": None, "webhook_configured": False}
    if key.startswith("sk_live_"):
        mode = "live"
    elif key.startswith("sk_test_"):
        mode = "test"
    else:
        mode = "unknown"
    return {
        "configured": True,
        "mode": mode,
        "webhook_configured": bool(settings.stripe_webhook_secret),
    }


@router.get("/accounts/pending-purge")
async def list_pending_purge(
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return every account that will be purged at the next cron tick."""
    service = DataRetentionService(db)
    candidates = await service.find_candidates()
    return [
        {
            "account_id": str(c.account_id),
            "account_name": c.account_name,
            "owner_email": c.owner_email,
            "reason": c.reason,
            "eligible_since": c.eligible_since.isoformat(),
        }
        for c in candidates
    ]


@router.get("/accounts/{account_id}/export")
async def export_account(
    account_id: uuid.UUID,
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GDPR art. 15 / 20 — return a JSON export of an account's data."""
    service = DataRetentionService(db)
    try:
        return await service.export_account(account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/accounts/{account_id}/erase")
async def erase_account(
    account_id: uuid.UUID,
    _: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """GDPR art. 17 — immediately and permanently delete an account."""
    service = DataRetentionService(db)
    try:
        summary = await service.purge_account(account_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return {"status": "erased", "account_id": str(account_id), "summary": summary}
