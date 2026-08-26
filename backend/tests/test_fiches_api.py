"""Tests de la liste des fiches pratiques."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.models.conversation import Message
from app.models.fiche import Fiche
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def test_list_fiches_includes_source_conversation(
    client: AsyncClient,
    manager_user: dict[str, str],
) -> None:
    organisation_response = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Organisation fiches"},
    )
    assert organisation_response.status_code == 201
    organisation_id = organisation_response.json()["id"]

    conversation_response = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(manager_user["token"]),
        json={"organisation_id": organisation_id, "title": "Question RH"},
    )
    assert conversation_response.status_code == 201
    conversation_id = conversation_response.json()["id"]

    async with session_factory() as session:
        user = (
            await session.execute(
                select(User).where(User.email == manager_user["email"])
            )
        ).scalar_one()
        message = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="assistant",
            content="Réponse source",
        )
        session.add(message)
        await session.flush()
        session.add_all(
            [
                Fiche(
                    organisation_id=uuid.UUID(organisation_id),
                    user_id=user.id,
                    message_id=message.id,
                    title="Fiche avec conversation",
                    content={},
                    sources=[],
                ),
                Fiche(
                    organisation_id=uuid.UUID(organisation_id),
                    user_id=user.id,
                    message_id=None,
                    title="Fiche historique",
                    content={},
                    sources=[],
                ),
            ]
        )
        await session.commit()

    response = await client.get(
        "/api/v1/fiches/",
        headers=auth_header(manager_user["token"]),
        params={"organisation_id": organisation_id},
    )

    assert response.status_code == 200
    fiches_by_title = {fiche["title"]: fiche for fiche in response.json()}
    assert (
        fiches_by_title["Fiche avec conversation"]["conversation_id"]
        == conversation_id
    )
    assert fiches_by_title["Fiche historique"]["conversation_id"] is None
