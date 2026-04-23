"""Billing / subscription API routes.

- `/billing/checkout` — start a Stripe Checkout session for a plan.
- `/billing/booster/checkout` — start a one-shot booster checkout.
- `/billing/portal` — open the Stripe Customer Portal for self-service.
- `/billing/webhook` — receive Stripe webhook events.
- `/billing/quota` — expose the current quota state to the authenticated user.
- `/billing/subscription` — return the current subscription summary.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import get_limits

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon
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
# Plan change (upgrade / downgrade from our own UI, bypasses the Portal)
# ---------------------------------------------------------------------------


class ChangePlanRequest(BaseModel):
    plan: str = Field(..., description="solo, equipe or groupe")
    cycle: str = Field(..., description="monthly or yearly")


@router.post("/change-plan")
async def change_plan(
    payload: ChangePlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Switch the active subscription to a new plan/cycle in-place.

    Used by the /billing catalog so upgrades (and safe downgrades) happen
    without creating a duplicate subscription via a fresh Checkout. Stripe
    handles the proration and the webhook mirrors the change.
    """
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    billing.ensure_plan_active(account)
    return await stripe_svc.change_plan(account, payload.plan, payload.cycle)


@router.post("/preview-change-plan")
async def preview_change_plan(
    payload: ChangePlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the prorated invoice preview for a candidate plan change.

    Called by the /billing UI before showing the confirmation dialog so
    the user sees the exact amount charged/credited before committing.
    """
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    billing.ensure_plan_active(account)
    return await stripe_svc.preview_change_plan(account, payload.plan, payload.cycle)


@router.post("/reactivate")
async def reactivate_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel a scheduled cancellation — the user keeps their plan."""
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    return await stripe_svc.reactivate_subscription(account)


@router.post("/cancel")
async def cancel_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel the active subscription at the end of the current period.

    The client keeps full access until ``current_period_end``. They can
    reactivate at any time before that date via /billing/reactivate.
    """
    billing = BillingService(db)
    stripe_svc = StripeService(db)

    account = await billing.get_primary_account_for_user(user)
    return await stripe_svc.cancel_subscription_at_period_end(account)


# ---------------------------------------------------------------------------
# Customer portal (self-service management)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Add-ons (self-service)
# ---------------------------------------------------------------------------


class AddAddonRequest(BaseModel):
    addon_type: str = Field(
        ..., description="extra_user, extra_org or extra_docs"
    )


@router.post("/addons")
async def add_addon(
    payload: AddAddonRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Increment an add-on quantity on the active subscription (+1).

    Returns the fresh SubscriptionAddon row. For user add-ons, we enforce
    the max_extra_users cap defined in plans.py before hitting Stripe.
    """
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)
    billing.ensure_plan_active(account)

    # Cap on extra_user based on plan config.
    if payload.addon_type == "extra_user":
        plan_limits = get_limits(account.plan)
        existing = await db.execute(
            select(SubscriptionAddon)
            .join(Subscription, Subscription.id == SubscriptionAddon.subscription_id)
            .where(
                Subscription.account_id == account.id,
                SubscriptionAddon.addon_type == "extra_user",
            )
        )
        row = existing.scalar_one_or_none()
        current_extra = row.quantity if row else 0
        if current_extra + 1 > plan_limits.max_extra_users:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Limite d'add-on utilisateurs atteinte ({plan_limits.max_extra_users} max). "
                    "Passez à l'offre supérieure pour plus d'utilisateurs inclus."
                ),
            )

    stripe_svc = StripeService(db)
    addon = await stripe_svc.add_addon(account, payload.addon_type, delta=1)
    return {
        "id": str(addon.id),
        "addon_type": addon.addon_type,
        "quantity": addon.quantity,
    }


@router.get("/addons")
async def list_addons(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List active add-ons on the current account."""
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)
    result = await db.execute(
        select(SubscriptionAddon)
        .join(Subscription, Subscription.id == SubscriptionAddon.subscription_id)
        .where(Subscription.account_id == account.id)
    )
    rows = []
    for addon in result.scalars():
        rows.append({
            "id": str(addon.id),
            "addon_type": addon.addon_type,
            "quantity": addon.quantity,
            "unit_price_cents": addon.unit_price_cents,
        })
    return rows


@router.delete("/addons/{addon_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_addon(
    addon_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Fully remove an add-on from the active subscription."""
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)
    stripe_svc = StripeService(db)
    await stripe_svc.remove_addon(account, addon_id)


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


@router.get("/usage-summary")
async def get_usage_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return aggregated usage counters for the current user's account:
    users, organisations, documents per organisation, questions.
    Consumed by the "Utilisation" panel on /billing.
    """
    billing = BillingService(db)
    account = await billing.get_primary_account_for_user(user)
    return await billing.get_usage_summary(account)


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
