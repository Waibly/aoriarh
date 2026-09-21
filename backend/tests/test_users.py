import pytest
from httpx import AsyncClient
from sqlalchemy import event, select

from app.models.conversation import Conversation, Message
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from tests.conftest import (
    auth_header,
    test_engine,
)
from tests.conftest import (
    test_session_factory as db_session_factory,
)


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.get("/api/v1/users/me", headers=auth_header(regular_user["token"]))
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "user@test.com"
    assert data["full_name"] == "Regular User"


@pytest.mark.asyncio
async def test_authenticated_context_does_not_load_conversation_history(
    client: AsyncClient, regular_user: dict[str, str]
):
    """Lightweight account endpoints must not hydrate chat messages."""
    async with db_session_factory() as session:
        user_id = (
            await session.execute(
                select(User.id).where(User.email == regular_user["email"])
            )
        ).scalar_one()
        organisation = Organisation(name="Organisation volumineuse")
        session.add(organisation)
        await session.flush()
        session.add(
            Membership(
                user_id=user_id,
                organisation_id=organisation.id,
                role_in_org="user",
            )
        )
        conversation = Conversation(
            organisation_id=organisation.id,
            user_id=user_id,
            title="Historique lourd",
        )
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content="Contenu qui ne doit pas être chargé",
            )
        )
        await session.commit()

    statements: list[str] = []

    def record_statement(*args) -> None:
        statements.append(args[2])

    event.listen(test_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        me_response = await client.get(
            "/api/v1/users/me", headers=auth_header(regular_user["token"])
        )
        organisations_response = await client.get(
            "/api/v1/organisations/", headers=auth_header(regular_user["token"])
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record_statement)

    assert me_response.status_code == 200
    assert organisations_response.status_code == 200
    normalized = [" ".join(statement.lower().split()) for statement in statements]
    assert not any(" from conversations " in statement for statement in normalized)
    assert not any(" from messages " in statement for statement in normalized)

    statements.clear()
    event.listen(test_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        conversations_response = await client.get(
            f"/api/v1/conversations/?organisation_id={organisation.id}",
            headers=auth_header(regular_user["token"]),
        )
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", record_statement)

    assert conversations_response.status_code == 200
    assert len(conversations_response.json()) == 1
    normalized = [" ".join(statement.lower().split()) for statement in statements]
    assert any(" from conversations " in statement for statement in normalized)
    assert not any(" from messages " in statement for statement in normalized)


@pytest.mark.asyncio
async def test_update_name(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.patch(
        "/api/v1/users/me",
        headers=auth_header(regular_user["token"]),
        json={"full_name": "Nouveau Nom"},
    )
    assert res.status_code == 200
    assert res.json()["full_name"] == "Nouveau Nom"


@pytest.mark.asyncio
async def test_update_email_conflict(
    client: AsyncClient, regular_user: dict[str, str], second_user: dict[str, str]
):
    res = await client.patch(
        "/api/v1/users/me",
        headers=auth_header(regular_user["token"]),
        json={"email": "user2@test.com"},
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_change_password_ok(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.post(
        "/api/v1/users/me/password",
        headers=auth_header(regular_user["token"]),
        json={"current_password": "SecurePass123!", "new_password": "NewPass456!xyz"},
    )
    assert res.status_code == 200
    assert res.json()["detail"] == "Mot de passe modifié"


@pytest.mark.asyncio
async def test_change_password_wrong_current(
    client: AsyncClient, regular_user: dict[str, str]
):
    res = await client.post(
        "/api/v1/users/me/password",
        headers=auth_header(regular_user["token"]),
        json={"current_password": "wrongpass", "new_password": "NewPass456!xyz"},
    )
    assert res.status_code == 400
