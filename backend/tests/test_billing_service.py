"""Unit tests for BillingService and plan_service.

These tests hit the service layer directly (no HTTP round-trip) and use
the SQLite in-memory database provided by conftest. Stripe is never
contacted: the few flows that need a Stripe customer are bypassed or
patched.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.plans import LIMITS_SOLO, LIMITS_EQUIPE
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.booster_purchase import BoosterPurchase
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.billing import QuotaStatus
from app.services.billing_service import BillingService
from app.services.plan_service import PlanOverflowError, assign_plan
from tests.conftest import auth_header, test_session_factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_account_for_email(email: str) -> Account:
    """Look up the Account owned by the test user with this email."""
    async with test_session_factory() as session:
        result = await session.execute(
            User.__table__.select().where(User.email == email)
        )
        user_row = result.first()
        account_result = await session.execute(
            Account.__table__.select().where(Account.owner_id == user_row.id)
        )
        row = account_result.first()
        return await session.get(Account, row.id)


async def _force_plan(email: str, plan: str) -> None:
    """Directly set a plan on the test user's account (bypasses validation)."""
    async with test_session_factory() as session:
        user_result = await session.execute(
            User.__table__.select().where(User.email == email)
        )
        user_row = user_result.first()
        await session.execute(
            update(Account)
            .where(Account.owner_id == user_row.id)
            .values(plan=plan, status="active", plan_expires_at=None)
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Quota: fair-use policy (never blocks, consumes boosters FIFO)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_gets_trial_account(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """Signup creates an Account in trial status with a 14-day expiry."""
    account = await _get_account_for_email(manager_user["email"])
    assert account.plan == "gratuit"
    assert account.status == "trialing"
    assert account.plan_expires_at is not None
    delta = account.plan_expires_at - account.plan_assigned_at
    assert 13 <= delta.days <= 14


@pytest.mark.asyncio
async def test_check_quota_ok_on_fresh_account(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    await _force_plan(manager_user["email"], "solo")
    account = await _get_account_for_email(manager_user["email"])

    async with test_session_factory() as session:
        billing = BillingService(session)
        info = await billing.check_question_quota(account)
        assert info.status == QuotaStatus.OK
        assert info.used == 0
        assert info.quota == LIMITS_SOLO.questions_per_month
        assert info.remaining == LIMITS_SOLO.questions_per_month


@pytest.mark.asyncio
async def test_increment_crosses_soft_then_hard_warning(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """Incrementing past 80% and 120% flips the status accordingly."""
    await _force_plan(manager_user["email"], "solo")
    account = await _get_account_for_email(manager_user["email"])

    async with test_session_factory() as session:
        billing = BillingService(session)
        usage = await billing.get_or_create_usage(account)

        # Push to 85% → soft_warning
        usage.questions_used = int(0.85 * LIMITS_SOLO.questions_per_month)
        await session.commit()

        info = await billing.check_question_quota(account)
        assert info.status == QuotaStatus.SOFT_WARNING

        # Push to 125% → hard_warning
        usage.questions_used = int(1.25 * LIMITS_SOLO.questions_per_month)
        await session.commit()

        info = await billing.check_question_quota(account)
        assert info.status == QuotaStatus.HARD_WARNING


@pytest.mark.asyncio
async def test_increment_never_blocks_even_over_quota(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """Fair-use policy: we always allow the question through."""
    await _force_plan(manager_user["email"], "solo")
    account = await _get_account_for_email(manager_user["email"])

    async with test_session_factory() as session:
        billing = BillingService(session)
        usage = await billing.get_or_create_usage(account)
        usage.questions_used = LIMITS_SOLO.questions_per_month + 50
        await session.commit()

        # increment must not raise
        await billing.increment_question_count(account)
        await session.refresh(usage)
        assert usage.questions_used == LIMITS_SOLO.questions_per_month + 51


@pytest.mark.asyncio
async def test_booster_consumed_only_after_monthly_quota(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """Monthly quota is always drained first; booster is FIFO fallback."""
    await _force_plan(manager_user["email"], "solo")
    account = await _get_account_for_email(manager_user["email"])

    async with test_session_factory() as session:
        billing = BillingService(session)

        # Start a booster with 500 questions
        booster = BoosterPurchase(
            account_id=account.id,
            questions_purchased=500,
            questions_remaining=500,
            price_cents=2500,
            purchased_at=datetime.now(UTC),
        )
        session.add(booster)
        await session.commit()

        # First question: drains monthly quota (was 0/300) → 1/300, booster untouched
        await billing.increment_question_count(account)
        usage = await billing.get_or_create_usage(account)
        await session.refresh(booster)
        assert usage.questions_used == 1
        assert booster.questions_remaining == 500

        # Exhaust the monthly quota
        usage.questions_used = LIMITS_SOLO.questions_per_month
        await session.commit()

        # Next question drains the booster, not the monthly
        await billing.increment_question_count(account)
        await session.refresh(usage)
        await session.refresh(booster)
        assert usage.questions_used == LIMITS_SOLO.questions_per_month
        assert booster.questions_remaining == 499


# ---------------------------------------------------------------------------
# Hard limits: users, orgs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_organisation_limit_solo_blocks_second(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """On Solo (1 org max), a second create must 403."""
    await _force_plan(manager_user["email"], "solo")

    res1 = await client.post(
        "/api/v1/organisations/",
        json={"name": "Org 1"},
        headers=auth_header(manager_user["token"]),
    )
    assert res1.status_code == 201

    res2 = await client.post(
        "/api/v1/organisations/",
        json={"name": "Org 2"},
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 403
    assert "Limite d'organisations" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_admin_bypasses_organisation_limit(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    """Admins are allowed to exceed the plan limits (staff accounts)."""
    await _force_plan(admin_user["email"], "solo")

    for i in range(3):
        res = await client.post(
            "/api/v1/organisations/",
            json={"name": f"Admin Org {i}"},
            headers=auth_header(admin_user["token"]),
        )
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# PlanOverflowError: downgrade blocked when existing data is too large
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_plan_rejects_downgrade_with_too_many_orgs(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """On Équipe we create 3 orgs then try to downgrade to Solo (max 1)."""
    await _force_plan(manager_user["email"], "equipe")

    for i in range(3):
        await client.post(
            "/api/v1/organisations/",
            json={"name": f"Org {i}"},
            headers=auth_header(manager_user["token"]),
        )

    account = await _get_account_for_email(manager_user["email"])
    async with test_session_factory() as session:
        with pytest.raises(PlanOverflowError) as exc_info:
            await assign_plan(session, account.id, "solo")
        reasons = exc_info.value.reasons
        assert any("organisations" in r for r in reasons)


@pytest.mark.asyncio
async def test_assign_plan_recalculates_quota_on_upgrade(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    """Upgrading mid-period must bump the current MonthlyQuestionUsage quota."""
    await _force_plan(manager_user["email"], "solo")
    account = await _get_account_for_email(manager_user["email"])

    async with test_session_factory() as session:
        billing = BillingService(session)
        usage = await billing.get_or_create_usage(account)
        assert usage.quota_for_period == LIMITS_SOLO.questions_per_month

    async with test_session_factory() as session:
        await assign_plan(session, account.id, "equipe")

    async with test_session_factory() as session:
        billing = BillingService(session)
        usage = await billing.get_or_create_usage(account)
        assert usage.quota_for_period == LIMITS_EQUIPE.questions_per_month
