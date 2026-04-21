"""Centralised billing / quota / limit service.

Responsibilities:
  - resolve the Account attached to an organisation or user;
  - compute the effective limits of a plan (base plan + active add-ons);
  - enforce hard limits on users, organisations, documents, conventions;
  - track and check the monthly question quota (fair-use policy: never
    blocks questions but flags soft/hard warnings so the caller can
    emit an upsell email or banner).
"""

import logging
import uuid
from calendar import monthrange
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.plans import get_limits, is_commercial


logger = logging.getLogger(__name__)

_PLAN_LABELS = {
    "gratuit": "Essai",
    "invite": "Invité",
    "vip": "VIP",
    "solo": "Solo",
    "equipe": "Équipe",
    "groupe": "Groupe",
}
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.booster_purchase import BoosterPurchase
from app.models.ccn import OrganisationConvention
from app.models.document import Document
from app.models.monthly_question_usage import MonthlyQuestionUsage
from app.models.organisation import Organisation
from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon
from app.models.user import User
from app.schemas.billing import (
    HARD_WARNING_RATIO,
    SOFT_WARNING_RATIO,
    QuotaInfo,
    QuotaStatus,
)


class BillingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Account resolution
    # ------------------------------------------------------------------

    async def get_primary_account_for_user(self, user: User) -> Account:
        """Return the account the user acts on by default (owner, then first membership)."""
        if user.owned_account is not None:
            return user.owned_account
        if user.account_memberships:
            account = await self.db.get(Account, user.account_memberships[0].account_id)
            if account is not None:
                return account
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aucun compte actif associé à cet utilisateur",
        )

    async def get_account_for_organisation(
        self, organisation_id: uuid.UUID
    ) -> Account:
        result = await self.db.execute(
            select(Organisation).where(Organisation.id == organisation_id)
        )
        org = result.scalar_one_or_none()
        if org is None or org.account_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organisation sans compte associé",
            )
        account = await self.db.get(Account, org.account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Compte non trouvé",
            )
        return account

    # ------------------------------------------------------------------
    # Effective limits (base plan + add-ons)
    # ------------------------------------------------------------------

    async def get_effective_limits(self, account: Account) -> dict[str, int | None]:
        base = get_limits(account.plan)
        limits: dict[str, int | None] = {
            "users_included": base.users_included,
            "orgs_included": base.orgs_included,
            "docs_per_org": base.docs_per_org,
            "ccn_per_org": base.ccn_per_org,
            "questions_per_month": base.questions_per_month,
            "max_extra_users": base.max_extra_users,
        }

        # Add-ons only make sense for commercial plans attached to a
        # Stripe subscription.
        if not is_commercial(account.plan):
            return limits

        sub = await self._get_active_subscription(account.id)
        if sub is None:
            return limits

        addons = await self.db.execute(
            select(SubscriptionAddon).where(
                SubscriptionAddon.subscription_id == sub.id
            )
        )
        for addon in addons.scalars():
            if addon.addon_type == "extra_user":
                limits["users_included"] = (limits["users_included"] or 0) + addon.quantity
            elif addon.addon_type == "extra_org":
                limits["orgs_included"] = (limits["orgs_included"] or 0) + addon.quantity
            elif addon.addon_type == "extra_docs":
                limits["docs_per_org"] = (limits["docs_per_org"] or 0) + 500 * addon.quantity

        return limits

    async def _get_active_subscription(
        self, account_id: uuid.UUID
    ) -> Subscription | None:
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.account_id == account_id,
                Subscription.status.in_(["active", "trialing", "past_due"]),
            )
        )
        return result.scalars().first()

    # ------------------------------------------------------------------
    # Lifecycle (expiration / suspension)
    # ------------------------------------------------------------------

    @staticmethod
    def is_plan_expired(account: Account) -> bool:
        if account.plan_expires_at is None:
            return False
        return account.plan_expires_at < datetime.now(UTC)

    def ensure_plan_active(self, account: Account) -> None:
        """Raise 402 if the account cannot consume the service right now."""
        if account.status == "suspended":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Votre compte est suspendu. Merci de régulariser votre abonnement.",
            )
        if self.is_plan_expired(account):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    "Votre période d'essai ou votre abonnement est arrivé à échéance. "
                    "Merci de souscrire à une offre pour continuer."
                ),
            )

    # ------------------------------------------------------------------
    # Quota period
    # ------------------------------------------------------------------

    @staticmethod
    def _current_period(account: Account) -> tuple[datetime, datetime]:
        """Return (start, end) of the current usage window.

        - For the 14-day trial (plan='gratuit'): [plan_assigned_at, plan_expires_at].
        - For every other plan: calendar month. Simple and predictable until
          we align periods on Stripe billing cycles.
        """
        now = datetime.now(UTC)
        if (
            account.plan == "gratuit"
            and account.plan_assigned_at is not None
            and account.plan_expires_at is not None
        ):
            return account.plan_assigned_at, account.plan_expires_at

        start = datetime(now.year, now.month, 1, tzinfo=UTC)
        last_day = monthrange(start.year, start.month)[1]
        end = datetime(start.year, start.month, last_day, 23, 59, 59, tzinfo=UTC)
        return start, end

    # ------------------------------------------------------------------
    # Monthly question usage
    # ------------------------------------------------------------------

    async def get_or_create_usage(
        self, account: Account
    ) -> MonthlyQuestionUsage:
        start, end = self._current_period(account)
        limits = await self.get_effective_limits(account)
        quota = int(limits["questions_per_month"] or 0)

        result = await self.db.execute(
            select(MonthlyQuestionUsage).where(
                MonthlyQuestionUsage.account_id == account.id,
                MonthlyQuestionUsage.period_start == start.date(),
            )
        )
        usage = result.scalar_one_or_none()
        if usage is None:
            usage = MonthlyQuestionUsage(
                account_id=account.id,
                period_start=start.date(),
                period_end=end.date(),
                questions_used=0,
                quota_for_period=quota,
            )
            self.db.add(usage)
            await self.db.flush()
        return usage

    async def check_question_quota(self, account: Account) -> QuotaInfo:
        """Return the current quota state without blocking anything."""
        self.ensure_plan_active(account)

        usage = await self.get_or_create_usage(account)
        booster_remaining = await self._active_booster_remaining(account.id)

        total_quota = usage.quota_for_period + booster_remaining
        used = usage.questions_used
        remaining = max(0, total_quota - used)

        ratio = (used / usage.quota_for_period) if usage.quota_for_period > 0 else 0
        if ratio >= HARD_WARNING_RATIO:
            quota_status = QuotaStatus.HARD_WARNING
        elif ratio >= SOFT_WARNING_RATIO:
            quota_status = QuotaStatus.SOFT_WARNING
        else:
            quota_status = QuotaStatus.OK

        return QuotaInfo(
            status=quota_status,
            used=used,
            quota=usage.quota_for_period,
            remaining=remaining,
            period_start=usage.period_start,
            period_end=usage.period_end,
            booster_remaining=booster_remaining,
        )

    async def increment_question_count(self, account: Account) -> None:
        """Record one additional question.

        First consumes from the monthly quota; if exhausted, consumes from
        the oldest available booster pack. If both are exhausted we still
        increment the monthly counter (fair-use: no blocking).

        Also sends the "you've exceeded your quota" upsell email the first
        time the account crosses the HARD_WARNING threshold for a given
        period. Best-effort: a Brevo failure must never break the chat.
        """
        usage = await self.get_or_create_usage(account)

        if usage.questions_used < usage.quota_for_period:
            usage.questions_used += 1
            await self.db.flush()
            return

        booster = await self._get_oldest_available_booster(account.id)
        if booster is not None:
            booster.questions_remaining -= 1
            await self.db.flush()
            return

        # Monthly quota and all boosters are gone — still increment (fair-use).
        usage.questions_used += 1
        await self.db.flush()

        # Trigger upsell email once per period when we cross 120 %.
        if (
            usage.hard_warning_email_sent_at is None
            and usage.quota_for_period > 0
            and usage.questions_used >= int(HARD_WARNING_RATIO * usage.quota_for_period)
        ):
            await self._send_hard_warning_email(account, usage)

    async def get_usage_summary(self, account: Account) -> dict:
        """Aggregate all usage counters (users, orgs, docs per org, questions)
        for a given account. Used by the public `GET /billing/usage-summary`
        endpoint so the client can see their footprint at a glance.
        """
        limits = await self.get_effective_limits(account)

        # Users (owner + members)
        members_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(AccountMember)
                    .where(AccountMember.account_id == account.id)
                )
            ).scalar()
            or 0
        )
        total_users = members_count + 1

        # Organisations
        orgs_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Organisation)
                    .where(Organisation.account_id == account.id)
                )
            ).scalar()
            or 0
        )

        # Documents per org
        docs_rows: list[dict] = []
        orgs_result = await self.db.execute(
            select(Organisation)
            .where(Organisation.account_id == account.id)
            .order_by(Organisation.name)
        )
        for org in orgs_result.scalars():
            used = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(Document)
                        .where(Document.organisation_id == org.id)
                    )
                ).scalar()
                or 0
            )
            docs_rows.append(
                {
                    "org_id": str(org.id),
                    "org_name": org.name,
                    "used": used,
                    "limit": int(limits["docs_per_org"] or 0),
                }
            )

        # Questions (current period)
        quota_info = await self.check_question_quota(account)

        return {
            "users": {"used": total_users, "limit": int(limits["users_included"] or 0)},
            "organisations": {
                "used": orgs_count,
                "limit": int(limits["orgs_included"] or 0),
            },
            "documents_by_org": docs_rows,
            "questions": {
                "used": quota_info.used,
                "limit": quota_info.quota,
                "booster_remaining": quota_info.booster_remaining,
                "period_start": quota_info.period_start.isoformat(),
                "period_end": quota_info.period_end.isoformat(),
                "quota_status": quota_info.status.value,
            },
        }

    async def _send_hard_warning_email(self, account: Account, usage) -> None:
        """Send the over-quota upsell email once per billing period."""
        try:
            from app.models.user import User as UserModel
            from app.services.email.sender import send_email
            from app.services.email.templates import render_quota_hard_warning_email

            owner = await self.db.get(UserModel, account.owner_id)
            if owner is None or not owner.is_active:
                return

            plan_label = _PLAN_LABELS.get(account.plan, account.plan)
            upgrade_url = f"{app_settings.frontend_url}/billing"
            subject, html = render_quota_hard_warning_email(
                full_name=owner.full_name,
                plan_label=plan_label,
                used=usage.questions_used,
                quota=usage.quota_for_period,
                upgrade_url=upgrade_url,
            )
            sent = await send_email(owner.email, owner.full_name, subject, html)
            if sent:
                usage.hard_warning_email_sent_at = datetime.now(UTC)
                await self.db.flush()
        except Exception:
            logger.exception(
                "Hard-warning email failed for account %s — swallowed so the chat request continues",
                account.id,
            )

    async def _active_booster_remaining(self, account_id: uuid.UUID) -> int:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(func.coalesce(func.sum(BoosterPurchase.questions_remaining), 0))
            .where(
                BoosterPurchase.account_id == account_id,
                BoosterPurchase.questions_remaining > 0,
                (BoosterPurchase.expires_at.is_(None))
                | (BoosterPurchase.expires_at > now),
            )
        )
        return int(result.scalar() or 0)

    async def _get_oldest_available_booster(
        self, account_id: uuid.UUID
    ) -> BoosterPurchase | None:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(BoosterPurchase)
            .where(
                BoosterPurchase.account_id == account_id,
                BoosterPurchase.questions_remaining > 0,
                (BoosterPurchase.expires_at.is_(None))
                | (BoosterPurchase.expires_at > now),
            )
            .order_by(BoosterPurchase.purchased_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Hard limits (block creation with 403 when exceeded)
    # ------------------------------------------------------------------

    async def _count_users_on_account(self, account_id: uuid.UUID) -> int:
        """Owner + every row in account_members."""
        result = await self.db.execute(
            select(func.count())
            .select_from(AccountMember)
            .where(AccountMember.account_id == account_id)
        )
        members = int(result.scalar() or 0)
        return members + 1  # +1 for the account owner (not in account_members)

    async def check_user_limit(self, account: Account) -> None:
        limits = await self.get_effective_limits(account)
        current = await self._count_users_on_account(account.id)
        cap = int(limits["users_included"] or 0)
        if current >= cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Limite d'utilisateurs atteinte ({cap}). "
                    "Passez à l'offre supérieure ou ajoutez un utilisateur additionnel."
                ),
            )

    async def check_organisation_limit(self, account: Account) -> None:
        limits = await self.get_effective_limits(account)
        result = await self.db.execute(
            select(func.count())
            .select_from(Organisation)
            .where(Organisation.account_id == account.id)
        )
        current = int(result.scalar() or 0)
        cap = int(limits["orgs_included"] or 0)
        if current >= cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Limite d'organisations atteinte ({cap}). "
                    "Passez à l'offre supérieure ou ajoutez une organisation additionnelle."
                ),
            )

    async def check_document_limit(self, organisation: Organisation) -> None:
        account = await self.get_account_for_organisation(organisation.id)
        limits = await self.get_effective_limits(account)
        result = await self.db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.organisation_id == organisation.id)
        )
        current = int(result.scalar() or 0)
        cap = int(limits["docs_per_org"] or 0)
        if current >= cap:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Limite de documents atteinte ({cap} par organisation). "
                    "Passez à l'offre supérieure ou ajoutez le pack +500 documents."
                ),
            )

    async def check_ccn_limit(self, organisation: Organisation) -> None:
        account = await self.get_account_for_organisation(organisation.id)
        limits = await self.get_effective_limits(account)
        cap = limits["ccn_per_org"]
        if cap is None:
            return  # unlimited (Groupe)
        result = await self.db.execute(
            select(func.count())
            .select_from(OrganisationConvention)
            .where(OrganisationConvention.organisation_id == organisation.id)
        )
        current = int(result.scalar() or 0)
        if current >= int(cap):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Limite de conventions collectives atteinte ({cap}). "
                    "Passez à l'offre Groupe pour un accès illimité."
                ),
            )
