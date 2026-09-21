from datetime import UTC, datetime

from sqlalchemy import select

from app.models.user import User
from tests.conftest import test_session_factory as _test_session_factory


async def test_clients_are_sorted_by_most_recent_signup_by_default(
    client, admin_user, regular_user
):
    older_signup = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
    newer_signup = datetime(2026, 2, 20, 15, 30, tzinfo=UTC)

    async with _test_session_factory() as session:
        admin = (
            await session.execute(select(User).where(User.email == admin_user["email"]))
        ).scalar_one()
        regular = (
            await session.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()
        admin.owned_account.created_at = older_signup
        regular.owned_account.created_at = newer_signup
        await session.commit()

    response = await client.get(
        "/api/v1/admin/business/clients",
        headers={"Authorization": f"Bearer {admin_user['token']}"},
    )

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert [row["owner_email"] for row in rows[:2]] == [
        regular_user["email"],
        admin_user["email"],
    ]
    assert rows[0]["registered_at"].startswith("2026-02-20T15:30:00")
