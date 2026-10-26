"""Technical contracts for the unified client navigation and its filters."""

import uuid

import pytest
from sqlalchemy import select

from app.models.subscription import Subscription
from app.models.user import User
from tests.conftest import test_session_factory as session_factory


async def test_client_filters_apply_before_pagination(client, admin_user, regular_user):
    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()
        user.owned_account.status = "past_due"
        account_id = str(user.owned_account.id)
        await session.commit()

    response = await client.get(
        "/api/v1/admin/business/clients",
        params={"q": "USER@TEST.COM", "status": "past_due", "page_size": 1},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert [row["account_id"] for row in result["rows"]] == [account_id]

    empty = await client.get(
        "/api/v1/admin/business/clients",
        params={"q": "client-absent"},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert empty.json()["total"] == 0


async def test_client_detail_scopes_all_three_views(client, admin_user, regular_user):
    async with session_factory() as session:
        users = list((await session.execute(select(User))).scalars())
        target_id = None
        for user in users:
            session.add(
                Subscription(account_id=user.owned_account.id, plan="solo", billing_cycle="monthly")
            )
            if user.email == regular_user["email"]:
                target_id = str(user.owned_account.id)
        await session.commit()
    assert target_id
    for path, collection in [
        ("/api/v1/admin/business/clients", "rows"),
        ("/api/v1/admin/workspaces/", "workspaces"),
        ("/api/v1/admin/billing/subscriptions", None),
    ]:
        response = await client.get(
            path,
            params={"account_id": target_id},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert response.status_code == 200
        body = response.json()
        rows = body[collection] if collection else body
        assert rows
        assert {row["account_id"] for row in rows} == {target_id}
        if collection == "workspaces":
            assert body["orphan_users"] == []


async def test_unknown_client_has_no_cross_account_fallback(client, admin_user):
    response = await client.get(
        "/api/v1/admin/business/clients",
        params={"account_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 200
    assert response.json()["rows"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/business/clients",
        "/api/v1/admin/workspaces/",
        "/api/v1/admin/billing/subscriptions",
    ],
)
async def test_client_views_keep_admin_authorization(client, regular_user, path):
    response = await client.get(path, headers={"Authorization": f"Bearer {regular_user['token']}"})
    assert response.status_code == 403


async def test_lowest_margins_can_be_requested_first(client, admin_user, regular_user):
    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()
        session.add(
            Subscription(account_id=user.owned_account.id, plan="solo", billing_cycle="monthly")
        )
        await session.commit()
    response = await client.get(
        "/api/v1/admin/business/clients",
        params={"sort": "margin", "direction": "asc", "page_size": 1},
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )
    assert response.status_code == 200
    assert response.json()["rows"][0]["owner_email"] == admin_user["email"]


async def test_subscription_pagination_keeps_the_client_filter(client, admin_user, regular_user):
    async with session_factory() as session:
        users = list((await session.execute(select(User))).scalars())
        account_id = None
        for user in users:
            for _ in range(2):
                session.add(
                    Subscription(
                        account_id=user.owned_account.id,
                        plan="solo",
                        billing_cycle="monthly",
                    )
                )
            if user.email == regular_user["email"]:
                account_id = str(user.owned_account.id)
        await session.commit()
    ids = []
    for offset in range(3):
        response = await client.get(
            "/api/v1/admin/billing/subscriptions",
            params={"account_id": account_id, "limit": 1, "offset": offset},
            headers={"Authorization": f"Bearer {admin_user['token']}"},
        )
        assert response.status_code == 200
        rows = response.json()
        if offset < 2:
            assert len(rows) == 1
            assert rows[0]["account_id"] == account_id
            ids.append(rows[0]["subscription_id"])
        else:
            assert rows == []
    assert len(set(ids)) == 2
