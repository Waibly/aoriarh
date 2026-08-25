"""Tests d'accès et d'indépendance de l'endpoint LinkedIn."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import func, select

from app.models.conversation import Message
from app.models.fiche import Fiche
from app.services.linkedin_post_service import LinkedInPostGeneration
from app.services.security_alert_service import EVENT_TECHNICAL_RECON
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def _create_conversation(
    client: AsyncClient,
    actor: dict,
    *,
    suffix: str,
) -> str:
    organisation = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(actor["token"]),
        json={"name": f"Organisation LinkedIn {suffix}"},
    )
    assert organisation.status_code == 201, organisation.text

    conversation = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(actor["token"]),
        json={"organisation_id": organisation.json()["id"], "title": None},
    )
    assert conversation.status_code == 201, conversation.text
    return conversation.json()["id"]


async def _add_exchange(
    conversation_id: str,
    *,
    answer: str = "L'article L. 1234-1 fixe la règle.",
    rag_trace: dict | None = None,
) -> tuple[str, list[dict]]:
    sources = [
        {
            "document_id": "00000000-0000-0000-0000-000000000010",
            "source_type": "code_travail",
            "source_type_label": "Code du travail",
            "document_name": "Code du travail",
            "article_nums": ["L.1234-1"],
            "excerpt": "Extrait",
        }
    ]
    now = datetime.now(UTC)
    async with session_factory() as session:
        question = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="user",
            content="Quel est le principe ?",
            created_at=now,
        )
        assistant = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="assistant",
            content=answer,
            sources=sources,
            rag_trace=rag_trace,
            created_at=now + timedelta(seconds=1),
        )
        session.add_all([question, assistant])
        await session.commit()
        await session.refresh(assistant)
        return str(assistant.id), sources


async def test_linkedin_endpoint_requires_global_admin_role(
    client: AsyncClient,
    manager_user: dict,
) -> None:
    response = await client.post(
        "/api/v1/conversations/messages/00000000-0000-0000-0000-000000000099/linkedin-post",
        headers=auth_header(manager_user["token"]),
    )

    assert response.status_code == 403


async def test_admin_receives_raw_post_without_mutating_chat_or_fiches(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="admin")
    message_id, sources = await _add_exchange(conversation_id)
    raw = "  Accroche\n\nCorps.\n\nSources :\n• Code du travail, art. L.1234-1\n\nVotre avis ?  "
    generation = LinkedInPostGeneration(
        content=raw,
        references=["Code du travail, art. L.1234-1"],
        warnings=[],
    )

    with patch(
        "app.services.linkedin_post_service.generate_linkedin_post",
        new=AsyncMock(return_value=generation),
    ) as generate:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/linkedin-post",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "content": raw,
        "character_count": len(raw),
        "references": ["Code du travail, art. L.1234-1"],
        "warnings": [],
    }
    call = generate.await_args.kwargs
    assert call["question"] == "Quel est le principe ?"
    assert call["answer_markdown"] == "L'article L. 1234-1 fixe la règle."
    assert call["sources"] == sources
    assert call["message_id"] == message_id

    async with session_factory() as session:
        persisted = await session.get(Message, uuid.UUID(message_id))
        fiche_count = await session.scalar(select(func.count(Fiche.id)))
    assert persisted is not None
    assert persisted.content == "L'article L. 1234-1 fixe la règle."
    assert persisted.sources == sources
    assert fiche_count == 0


async def test_admin_cannot_generate_from_another_users_conversation(
    client: AsyncClient,
    admin_user: dict,
    manager_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, manager_user, suffix="client")
    message_id, _ = await _add_exchange(conversation_id)

    with patch(
        "app.services.linkedin_post_service.generate_linkedin_post",
        new=AsyncMock(),
    ) as generate:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/linkedin-post",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 403
    generate.assert_not_awaited()


async def test_security_response_never_reaches_linkedin_llm(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="security")
    message_id, _ = await _add_exchange(
        conversation_id,
        answer="Réponse de sécurité déterministe",
        rag_trace={"security_event": EVENT_TECHNICAL_RECON},
    )

    with patch(
        "app.services.linkedin_post_service.generate_linkedin_post",
        new=AsyncMock(),
    ) as generate:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/linkedin-post",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 422
    assert "réponse de sécurité" in response.json()["detail"]
    generate.assert_not_awaited()
