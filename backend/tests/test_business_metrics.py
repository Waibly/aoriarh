"""Calculs du cockpit admin : revenu mensuel, résiliation, conversion, activité."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as _session_factory


async def _account_id(email: str):
    async with _session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        return user.owned_account.id


async def _overview(client, token: str) -> dict:
    response = await client.get("/api/v1/admin/business/overview", headers=auth_header(token))
    assert response.status_code == 200, response.text
    return response.json()


async def test_mrr_includes_recurring_addons_and_spreads_yearly(
    client, admin_user, regular_user, second_user
):
    regular = await _account_id(regular_user["email"])
    second = await _account_id(second_user["email"])
    async with _session_factory() as session:
        monthly = Subscription(
            account_id=regular, plan="solo", billing_cycle="monthly", status="active"
        )
        yearly = Subscription(
            account_id=second, plan="equipe", billing_cycle="yearly", status="active"
        )
        session.add_all([monthly, yearly])
        await session.flush()
        session.add(
            SubscriptionAddon(
                subscription_id=monthly.id,
                addon_type="extra_user",
                quantity=2,
                unit_price_cents=1500,
            )
        )
        await session.commit()

    data = await _overview(client, admin_user["token"])
    # 79 + 2 × 15 + 1490 / 12 (124,16)
    assert data["mrr_eur"] == 79 + 30 + 124.16
    assert data["arr_eur"] == round((79 + 30 + 124.16) * 12, 2)

    rows = (
        await client.get("/api/v1/admin/business/clients", headers=auth_header(admin_user["token"]))
    ).json()["rows"]
    by_email = {r["owner_email"]: r["mrr_eur"] for r in rows}
    assert by_email[regular_user["email"]] == 109


async def test_churn_counts_effective_end_not_cancellation_request(
    client, admin_user, regular_user, second_user
):
    regular = await _account_id(regular_user["email"])
    second = await _account_id(second_user["email"])
    now = datetime.now(UTC)
    async with _session_factory() as session:
        # Résiliation demandée il y a 45 jours, abonnement terminé il y a 5 jours.
        ended = Subscription(
            account_id=regular,
            plan="solo",
            billing_cycle="monthly",
            status="active",
            created_at=now - timedelta(days=200),
            canceled_at=now - timedelta(days=45),
        )
        still_live = Subscription(
            account_id=second,
            plan="solo",
            billing_cycle="monthly",
            status="active",
            created_at=now - timedelta(days=100),
        )
        session.add_all([ended, still_live])
        await session.flush()
        ended.status = "canceled"
        await session.flush()
        assert ended.ended_at is not None
        ended.ended_at = now - timedelta(days=5)
        await session.commit()

    data = await _overview(client, admin_user["token"])
    assert data["subscriptions_ended_30d"] == 1
    # 1 terminé sur 2 abonnements actifs il y a 30 jours
    assert data["monthly_churn_pct"] == 50.0


async def test_churn_is_unknown_without_subscription_base(client, admin_user):
    data = await _overview(client, admin_user["token"])
    assert data["monthly_churn_pct"] is None


async def test_scheduled_cancellation_is_listed_to_handle(client, admin_user, regular_user):
    regular = await _account_id(regular_user["email"])
    async with _session_factory() as session:
        session.add(
            Subscription(
                account_id=regular,
                plan="solo",
                billing_cycle="monthly",
                status="active",
                cancel_at_period_end=True,
                current_period_end=datetime(2026, 12, 20, tzinfo=UTC),
            )
        )
        await session.commit()

    data = await _overview(client, admin_user["token"])
    scheduled = [a for a in data["at_risk"] if a["reason"] == "cancel_scheduled"]
    assert len(scheduled) == 1
    assert scheduled[0]["detail"] == "Fin le 20/12/2026"


async def test_trial_conversion_uses_finished_trial_cohort(
    client, admin_user, regular_user, second_user, manager_user
):
    now = datetime.now(UTC)
    regular = await _account_id(regular_user["email"])
    second = await _account_id(second_user["email"])
    manager = await _account_id(manager_user["email"])
    async with _session_factory() as session:
        for user_id_email, created in (
            (regular_user["email"], now - timedelta(days=20)),  # essai terminé
            (second_user["email"], now - timedelta(days=25)),  # essai terminé
            (manager_user["email"], now - timedelta(days=3)),  # essai en cours
        ):
            user = (
                await session.execute(select(User).where(User.email == user_id_email))
            ).scalar_one()
            user.owned_account.created_at = created
        # Le premier a payé ; celui en essai a payé aussi mais n'est pas dans la cohorte.
        session.add_all(
            [
                Subscription(
                    account_id=regular, plan="solo", billing_cycle="monthly", status="active"
                ),
                Subscription(
                    account_id=manager, plan="solo", billing_cycle="monthly", status="active"
                ),
            ]
        )
        await session.commit()
    assert second

    data = await _overview(client, admin_user["token"])
    assert data["trials_finished_30d"] == 2
    assert data["trials_converted_30d"] == 1
    assert data["trial_to_paid_rate_30d"] == 0.5


async def test_resubscription_is_not_a_new_customer(client, admin_user, regular_user):
    regular = await _account_id(regular_user["email"])
    now = datetime.now(UTC)
    async with _session_factory() as session:
        session.add_all(
            [
                Subscription(
                    account_id=regular,
                    plan="solo",
                    billing_cycle="monthly",
                    status="canceled",
                    created_at=now - timedelta(days=90),
                ),
                Subscription(
                    account_id=regular,
                    plan="solo",
                    billing_cycle="monthly",
                    status="active",
                    created_at=now - timedelta(days=2),
                ),
            ]
        )
        await session.commit()

    data = await _overview(client, admin_user["token"])
    assert data["new_customers_30d"] == 0


async def test_dashboard_timeline_has_thirty_days_and_real_active_users(
    client, admin_user, regular_user
):
    response = await client.get(
        "/api/v1/admin/dashboard/", headers=auth_header(admin_user["token"])
    )
    assert response.status_code == 200, response.text
    data = response.json()
    timeline = data["questions_timeline_30d"]
    assert len(timeline) == 30
    assert all(point["questions"] == 0 for point in timeline)
    # Personne n'a posé de question : aucun utilisateur actif.
    assert data["active_users"] == 0
    assert data["total_users"] >= 2
