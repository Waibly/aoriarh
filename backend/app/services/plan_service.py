import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plans import get_limits
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.ccn import OrganisationConvention
from app.models.document import Document
from app.models.monthly_question_usage import MonthlyQuestionUsage
from app.models.organisation import Organisation


class PlanOverflowError(Exception):
    """Raised when assigning a plan that cannot contain the existing data.

    The caller (typically an admin endpoint) turns this into a 409 with
    the ``reasons`` list, so the admin can see exactly what to clean up
    before retrying.
    """

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


async def resolve_expired_plans(db: AsyncSession) -> int:
    """Batch-revoke expired invite plans back to gratuit. Returns count of revoked."""
    result = await db.execute(
        update(Account)
        .where(Account.plan == "invite", Account.plan_expires_at < datetime.now(UTC))
        .values(plan="gratuit", plan_expires_at=None)
    )
    return result.rowcount


async def _validate_plan_fits_existing_data(
    db: AsyncSession, account_id: uuid.UUID, plan: str
) -> None:
    """Raise PlanOverflowError if the new plan is too small for what already exists.

    Called before any plan change so we never leave an account in a state
    where the user already has more resources than their new plan allows.
    Counts done without locking — a concurrent creation could squeeze
    past, but all creation endpoints re-check at write time.
    """
    limits = get_limits(plan)
    reasons: list[str] = []

    # Users (owner + account_members)
    members_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(AccountMember)
                .where(AccountMember.account_id == account_id)
            )
        ).scalar()
        or 0
    )
    total_users = members_count + 1  # +1 owner
    if total_users > limits.users_included:
        reasons.append(
            f"utilisateurs actifs : {total_users} (plan {plan} en autorise {limits.users_included})"
        )

    # Organisations
    orgs_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Organisation)
                .where(Organisation.account_id == account_id)
            )
        ).scalar()
        or 0
    )
    if orgs_count > limits.orgs_included:
        reasons.append(
            f"organisations : {orgs_count} (plan {plan} en autorise {limits.orgs_included})"
        )

    # Documents per organisation (and CCN per organisation) —
    # we check against every org of the account individually, since
    # the limit is per-org.
    orgs_result = await db.execute(
        select(Organisation).where(Organisation.account_id == account_id)
    )
    for org in orgs_result.scalars():
        docs_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.organisation_id == org.id)
                )
            ).scalar()
            or 0
        )
        if docs_count > limits.docs_per_org:
            reasons.append(
                f"documents dans '{org.name}' : {docs_count} "
                f"(plan {plan} en autorise {limits.docs_per_org} par organisation)"
            )

        if limits.ccn_per_org is not None:
            ccn_count = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(OrganisationConvention)
                        .where(OrganisationConvention.organisation_id == org.id)
                    )
                ).scalar()
                or 0
            )
            if ccn_count > limits.ccn_per_org:
                reasons.append(
                    f"conventions dans '{org.name}' : {ccn_count} "
                    f"(plan {plan} en autorise {limits.ccn_per_org} par organisation)"
                )

    if reasons:
        raise PlanOverflowError(reasons)


async def assign_plan(
    db: AsyncSession,
    account_id: uuid.UUID,
    plan: str,
    duration_months: int | None = None,
) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise ValueError("Account non trouvé")

    # Block the change if the new plan is too small for what already exists.
    # Admins may still deal with an overflow manually (delete the excess
    # users / orgs first) before retrying.
    await _validate_plan_fits_existing_data(db, account_id, plan)

    account.plan = plan
    account.plan_assigned_at = datetime.now(UTC)

    if plan == "invite" and duration_months:
        account.plan_expires_at = datetime.now(UTC) + timedelta(days=30 * duration_months)
    else:
        account.plan_expires_at = None

    # If the new plan has a larger question quota than the one snapshot
    # on the current billing period, upgrade the quota in place so the
    # client benefits from the extra allowance immediately — not only
    # from next month. We never downgrade an already-snapshot quota
    # mid-period (the client "paid" for that quota).
    new_limits = get_limits(plan)
    result = await db.execute(
        select(MonthlyQuestionUsage)
        .where(MonthlyQuestionUsage.account_id == account_id)
        .order_by(MonthlyQuestionUsage.period_start.desc())
        .limit(1)
    )
    current_usage = result.scalar_one_or_none()
    if (
        current_usage is not None
        and current_usage.quota_for_period < new_limits.questions_per_month
    ):
        current_usage.quota_for_period = new_limits.questions_per_month

    await db.commit()
    await db.refresh(account)
    return account
