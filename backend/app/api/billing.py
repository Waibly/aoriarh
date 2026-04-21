"""Billing / subscription API routes.

- `/billing/checkout` — start a Stripe Checkout session for a plan.
- `/billing/booster/checkout` — start a one-shot booster checkout.
- `/billing/portal` — open the Stripe Customer Portal for self-service.
- `/billing/webhook` — receive Stripe webhook events.
- `/billing/quota` — expose the current quota state to the authenticated user.
- `/billing/subscription` — return the current subscription summary.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.stripe_billing import (
    BoosterCheckoutResponse,
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    QuotaResponse,
    SubscriptionRead,
)
from app.services.billing_service import BillingService
from app.services.stripe_service import StripeService

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@router.post("/checkout", response_model=CheckoutResponse)
async def start_checkout(
    payload: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    result = await stripe_svc.create_subscription_checkout(
        account=account,
        owner_email=user.email,
        plan=payload.plan.value,
        cycle=payload.cycle.value,
    )
    return CheckoutResponse(
        checkout_url=result["checkout_url"],
        session_id=result["session_id"],
    )


@router.post("/booster/checkout", response_model=BoosterCheckoutResponse)
async def start_booster_checkout(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoosterCheckoutResponse:
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    result = await stripe_svc.create_booster_checkout(
        account=account, owner_email=user.email
    )
    return BoosterCheckoutResponse(
        checkout_url=result["checkout_url"],
        session_id=result["session_id"],
    )


# ---------------------------------------------------------------------------
# Customer portal (self-service management)
# ---------------------------------------------------------------------------


@router.post("/portal", response_model=PortalResponse)
async def open_portal(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalResponse:
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    portal_url = await stripe_svc.create_portal_session(account)
    return PortalResponse(portal_url=portal_url)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    stripe_svc = StripeService(db)
    event = stripe_svc.verify_webhook(payload, signature)
    await stripe_svc.handle_webhook_event(event)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Read-only views (quota + current subscription)
# ---------------------------------------------------------------------------


@router.get("/quota", response_model=QuotaResponse)
async def get_current_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuotaResponse:
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)

    info = await billing.check_question_quota(account)

    return QuotaResponse(
        plan=account.plan,
        status=account.status,
        used=info.used,
        quota=info.quota,
        remaining=info.remaining,
        booster_remaining=info.booster_remaining,
        period_start=info.period_start.isoformat(),
        period_end=info.period_end.isoformat(),
        quota_status=info.status.value,
        trial_ends_at=(
            account.plan_expires_at.isoformat() if account.plan_expires_at else None
        ),
    )


@router.get("/subscription", response_model=SubscriptionRead | None)
async def get_current_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionRead | None:
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)

    result = await db.execute(
        select(Subscription)
        .where(Subscription.account_id == account.id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return None
    return SubscriptionRead(
        plan=sub.plan,
        billing_cycle=sub.billing_cycle,
        status=sub.status,
        current_period_end=(
            sub.current_period_end.isoformat() if sub.current_period_end else None
        ),
        cancel_at_period_end=sub.cancel_at_period_end,
    )
