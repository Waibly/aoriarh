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
            await session.execute(select(User).where(User.email == manager_user["email"]))
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
    assert fiches_by_title["Fiche avec conversation"]["conversation_id"] == conversation_id
    assert fiches_by_title["Fiche historique"]["conversation_id"] is None


async def test_list_fiches_hides_link_to_deleted_conversation(
    client: AsyncClient,
    manager_user: dict[str, str],
) -> None:
    from datetime import UTC, datetime

    from app.models.conversation import Conversation

    organisation_response = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Organisation fiches masquées"},
    )
    organisation_id = organisation_response.json()["id"]
    conversation_response = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(manager_user["token"]),
        json={"organisation_id": organisation_id, "title": "Supprimée"},
    )
    conversation_id = conversation_response.json()["id"]

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == manager_user["email"]))
        ).scalar_one()
        conversation = await session.get(Conversation, uuid.UUID(conversation_id))
        conversation.hidden_at = datetime.now(UTC)
        message = Message(
            conversation_id=uuid.UUID(conversation_id), role="assistant", content="Réponse"
        )
        session.add(message)
        await session.flush()
        session.add(
            Fiche(
                organisation_id=uuid.UUID(organisation_id),
                user_id=user.id,
                message_id=message.id,
                title="Fiche orpheline",
                content={},
                sources=[],
            )
        )
        await session.commit()

    response = await client.get(
        "/api/v1/fiches/",
        headers=auth_header(manager_user["token"]),
        params={"organisation_id": organisation_id},
    )
    assert response.status_code == 200
    [fiche] = response.json()
    assert fiche["conversation_id"] is None


async def test_generate_fiche_upserts_and_exposes_fiche_id(
    client: AsyncClient,
    manager_user: dict[str, str],
) -> None:
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, patch

    from app.services.fiche_service import FicheContent

    organisation_response = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Organisation génération"},
    )
    organisation_id = organisation_response.json()["id"]
    conversation_response = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(manager_user["token"]),
        json={"organisation_id": organisation_id, "title": "Préavis"},
    )
    conversation_id = conversation_response.json()["id"]

    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Message(
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content="Quel préavis pour un CDI ?",
                    created_at=now - timedelta(minutes=3),
                ),
                Message(
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content="Et pour un CDD ?",
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        answer = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="assistant",
            content="En CDD, pas de préavis de démission.",
            created_at=now,
        )
        session.add(answer)
        await session.commit()
        answer_id = str(answer.id)

    body = '<article class="fiche-content"><h1>Démission en CDD</h1><p>Texte</p></article>'
    generate = AsyncMock(
        side_effect=lambda **_: FicheContent(titre="Démission en CDD", body_html=body)
    )
    with patch("app.services.fiche_service.generate_fiche_content", new=generate):
        first = await client.post(
            f"/api/v1/conversations/messages/{answer_id}/fiche",
            headers=auth_header(manager_user["token"]),
        )
        second = await client.post(
            f"/api/v1/conversations/messages/{answer_id}/fiche",
            headers=auth_header(manager_user["token"]),
        )

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/pdf"
    assert first.headers["x-fiche-truncated"] == "0"
    assert second.headers["x-fiche-id"] == first.headers["x-fiche-id"]
    kwargs = generate.await_args.kwargs
    assert kwargs["question"] == "Et pour un CDD ?"
    assert kwargs["previous_questions"] == ["Quel préavis pour un CDI ?"]

    listing = await client.get(
        "/api/v1/fiches/",
        headers=auth_header(manager_user["token"]),
        params={"organisation_id": organisation_id},
    )
    assert len(listing.json()) == 1

    conversation = await client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=auth_header(manager_user["token"]),
    )
    by_id = {m["id"]: m for m in conversation.json()["messages"]}
    assert by_id[answer_id]["fiche_id"] == first.headers["x-fiche-id"]
