import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


async def resolve_expired_plans(db: AsyncSession) -> int:
    """Batch-revoke expired invite plans back to gratuit. Returns count of revoked."""
    result = await db.execute(
        update(Account)
        .where(Account.plan == "invite", Account.plan_expires_at < datetime.now(UTC))
        .values(plan="gratuit", plan_expires_at=None)
    )
    return result.rowcount


async def assign_plan(
    db: AsyncSession,
    account_id: uuid.UUID,
    plan: str,
    duration_months: int | None = None,
) -> Account:
    account = await db.get(Account, account_id)
    if account is None:
        raise ValueError("Account non trouvé")

    account.plan = plan
    account.plan_assigned_at = datetime.now(UTC)

    if plan == "invite" and duration_months:
        account.plan_expires_at = datetime.now(UTC) + timedelta(days=30 * duration_months)
    else:
        account.plan_expires_at = None

    await db.commit()
    await db.refresh(account)
    return account
