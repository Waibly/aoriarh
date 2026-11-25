"""Business metrics shared by the admin cockpit and the billing endpoints.

Single place for the revenue / churn / acquisition formulas so that every admin
screen shows the same figures.

Conventions:
  - MRR = recurring amount of live subscriptions (active, trialing, past_due),
    excluding VAT: plan price (yearly ÷ 12) + recurring add-ons. One-off
    discounts (e.g. a first-month promo code) are not part of MRR, which is
    the standard SaaS convention: they do not recur.
  - Churn (30 d) = subscriptions that actually ENDED in the last 30 days divided
    by the subscriptions live at the start of the window. A cancellation
    scheduled at period end only counts once the subscription has ended.
  - Internal activity (staff accounts and the public demo) is excluded from
    product-value metrics so that they reflect customers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import PRICE_MONTHLY_CENTS, PRICE_YEARLY_CENTS, TRIAL_DURATION_DAYS
from app.models.account import Account
from app.models.conversation import Conversation
from app.models.organisation import Organisation
from app.models.plan_invitation import PlanInvitationRedemption
from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon
from app.models.user import User

LIVE_SUB_STATUSES = ("active", "trialing", "past_due")


def plan_mrr_cents(plan: str, billing_cycle: str) -> int:
    """Monthly value of the plan itself (yearly price spread over 12 months)."""
    if billing_cycle == "monthly":
        return PRICE_MONTHLY_CENTS.get(plan, 0)
    return PRICE_YEARLY_CENTS.get(plan, 0) // 12


def addons_mrr_cents(addons: list[SubscriptionAddon]) -> int:
    """Add-ons are billed monthly: unit price × quantity."""
    return sum((a.unit_price_cents or 0) * (a.quantity or 0) for a in addons)


async def addons_by_subscription(
    db: AsyncSession, subscription_ids: list[Any]
) -> dict[Any, list[SubscriptionAddon]]:
    if not subscription_ids:
        return {}
    rows = (
        await db.execute(
            select(SubscriptionAddon).where(SubscriptionAddon.subscription_id.in_(subscription_ids))
        )
    ).scalars()
    out: dict[Any, list[SubscriptionAddon]] = {}
    for addon in rows:
        out.setdefault(addon.subscription_id, []).append(addon)
    return out


@dataclass
class RevenueSnapshot:
    live_subs: list[Subscription]
    mrr_cents: int = 0
    by_plan: dict[str, int] = field(default_factory=dict)
    by_account_cents: dict[Any, int] = field(default_factory=dict)
    by_subscription_cents: dict[Any, int] = field(default_factory=dict)


async def revenue_snapshot(db: AsyncSession) -> RevenueSnapshot:
    live_subs = list(
        (
            await db.execute(select(Subscription).where(Subscription.status.in_(LIVE_SUB_STATUSES)))
        ).scalars()
    )
    addons = await addons_by_subscription(db, [s.id for s in live_subs])
    snap = RevenueSnapshot(live_subs=live_subs, by_plan={"solo": 0, "equipe": 0, "groupe": 0})
    for sub in live_subs:
        value = plan_mrr_cents(sub.plan, sub.billing_cycle) + addons_mrr_cents(
            addons.get(sub.id, [])
        )
        snap.mrr_cents += value
        snap.by_plan[sub.plan] = snap.by_plan.get(sub.plan, 0) + 1
        snap.by_account_cents[sub.account_id] = snap.by_account_cents.get(sub.account_id, 0) + value
        snap.by_subscription_cents[sub.id] = value
    return snap


@dataclass
class ChurnSnapshot:
    ended: int
    base: int
    pct: float | None


async def churn_30d(db: AsyncSession, now: datetime) -> ChurnSnapshot:
    """Subscriptions that ended in the last 30 days / subscriptions live 30 days ago."""
    start = now - timedelta(days=30)
    ended = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.status == "canceled",
                    Subscription.ended_at.isnot(None),
                    Subscription.ended_at >= start,
                )
            )
        ).scalar()
        or 0
    )
    base = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.created_at < start,
                    or_(
                        Subscription.status.in_(LIVE_SUB_STATUSES),
                        and_(
                            Subscription.status == "canceled",
                            Subscription.ended_at.isnot(None),
                            Subscription.ended_at >= start,
                        ),
                    ),
                )
            )
        ).scalar()
        or 0
    )
    pct = round(100 * ended / base, 1) if base > 0 else None
    return ChurnSnapshot(ended=ended, base=base, pct=pct)


def _staff_owned_account_ids():
    return select(Account.id).join(User, User.id == Account.owner_id).where(User.role == "admin")


async def new_customers(db: AsyncSession, since: datetime) -> int:
    """Accounts whose FIRST paid subscription started after ``since``.

    A customer who re-subscribes after cancelling is not counted again.
    """
    first_sub = (
        select(
            Subscription.account_id,
            func.min(Subscription.created_at).label("first_at"),
        )
        .group_by(Subscription.account_id)
        .subquery()
    )
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(first_sub)
                .where(
                    first_sub.c.first_at >= since,
                    first_sub.c.account_id.notin_(_staff_owned_account_ids()),
                )
            )
        ).scalar()
        or 0
    )


@dataclass
class TrialConversion:
    finished_trials: int
    converted: int
    rate: float | None


async def trial_conversion_30d(db: AsyncSession, now: datetime) -> TrialConversion:
    """Cohort conversion: of the trials that ENDED in the last 30 days, how many paid.

    Cohort = accounts created between 30+N and N days ago (N = trial length),
    i.e. whose trial ended during the last 30 days. Promo-link accounts (plan
    Invité) and staff accounts are left out: they never went through the trial.
    Converted = the account has at least one paid subscription.
    """
    trial = timedelta(days=TRIAL_DURATION_DAYS)
    cohort_start = now - timedelta(days=30) - trial
    cohort_end = now - trial
    promo_accounts = select(PlanInvitationRedemption.account_id)
    has_sub = exists().where(Subscription.account_id == Account.id)
    row = (
        await db.execute(
            select(
                func.count(Account.id),
                func.count(Account.id).filter(has_sub),
            ).where(
                Account.created_at >= cohort_start,
                Account.created_at < cohort_end,
                Account.id.notin_(promo_accounts),
                Account.id.notin_(_staff_owned_account_ids()),
            )
        )
    ).one()
    finished, converted = int(row[0] or 0), int(row[1] or 0)
    rate = round(converted / finished, 4) if finished > 0 else None
    return TrialConversion(finished_trials=finished, converted=converted, rate=rate)


def customer_conversation_filter():
    """SQL conditions keeping only customer conversations.

    Requires ``Conversation`` to be joined. Excludes conversations of staff
    users (role admin) and of the public demo organisation.
    """
    staff_ids = select(User.id).where(User.role == "admin")
    demo_org_ids = select(Organisation.id).where(Organisation.name == settings.demo_org_name)
    return [
        or_(Conversation.user_id.is_(None), Conversation.user_id.notin_(staff_ids)),
        or_(
            Conversation.organisation_id.is_(None),
            Conversation.organisation_id.notin_(demo_org_ids),
        ),
    ]
