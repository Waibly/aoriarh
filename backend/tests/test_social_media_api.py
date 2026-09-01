"""Tests d'accès et de fidélité des endpoints de média social."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.models.conversation import Message
from app.services.security_alert_service import EVENT_TECHNICAL_RECON
from app.services.social_media_service import RenderedMediaImage, SocialMediaGeneration
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def _create_conversation(client: AsyncClient, actor: dict, *, suffix: str) -> str:
    organisation = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(actor["token"]),
        json={"name": f"Organisation Média {suffix}"},
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
    rag_trace: dict | None = None,
) -> str:
    now = datetime.now(UTC)
    async with session_factory() as session:
        question = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="user",
            content="Quelle procédure appliquer ?",
            created_at=now,
        )
        assistant = Message(
            conversation_id=uuid.UUID(conversation_id),
            role="assistant",
            content="Voici la procédure à appliquer.",
            sources=[],
            rag_trace=rag_trace,
            created_at=now + timedelta(seconds=1),
        )
        session.add_all([question, assistant])
        await session.commit()
        await session.refresh(assistant)
        return str(assistant.id)


async def test_social_media_endpoint_requires_admin(
    client: AsyncClient,
    manager_user: dict,
) -> None:
    generation_response = await client.post(
        "/api/v1/conversations/messages/00000000-0000-0000-0000-000000000099/social-media",
        headers=auth_header(manager_user["token"]),
    )
    render_response = await client.post(
        "/api/v1/conversations/messages/00000000-0000-0000-0000-000000000099/social-media/render",
        headers=auth_header(manager_user["token"]),
        json={"html": "<html></html>"},
    )
    pdf_response = await client.post(
        "/api/v1/conversations/messages/00000000-0000-0000-0000-000000000099/social-media/pdf",
        headers=auth_header(manager_user["token"]),
        json={"html": "<html></html>"},
    )

    assert generation_response.status_code == 403
    assert render_response.status_code == 403
    assert pdf_response.status_code == 403


async def test_admin_receives_exact_raw_html_and_png(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="admin")
    message_id = await _add_exchange(conversation_id)
    raw = '  <main class="carousel"><section class="slide">Brut</section></main>  '
    html = f"<!doctype html><body>{raw}</body>"
    generation = SocialMediaGeneration(
        raw_content=raw,
        html=html,
        references=[],
        warnings=["Avertissement visible"],
    )
    png = b"\x89PNG\r\n\x1a\ncontenu"

    with (
        patch(
            "app.services.social_media_service.generate_social_media",
            new=AsyncMock(return_value=generation),
        ) as generate,
        patch(
            "app.services.social_media_service.render_social_media_pngs",
            new=MagicMock(
                return_value=[RenderedMediaImage(filename="aoria-media-01.png", content=png)]
            ),
        ) as render,
    ):
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "raw_content": raw,
        "html": html,
        "images": [
            {
                "filename": "aoria-media-01.png",
                "content_base64": base64.b64encode(png).decode("ascii"),
            }
        ],
        "references": [],
        "warnings": ["Avertissement visible"],
        "render_error": None,
    }
    assert generate.await_args.kwargs["question"] == "Quelle procédure appliquer ?"
    assert generate.await_args.kwargs["answer_markdown"] == "Voici la procédure à appliquer."
    render.assert_called_once_with(html)


async def test_png_failure_keeps_non_empty_llm_output_visible(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="png-failure")
    message_id = await _add_exchange(conversation_id)
    raw = '  <main class="carousel"><section class="slide">Toujours visible</section></main>  '
    html = f"<!doctype html><body>{raw}</body>"
    generation = SocialMediaGeneration(
        raw_content=raw,
        html=html,
        references=[],
        warnings=[],
    )

    with (
        patch(
            "app.services.social_media_service.generate_social_media",
            new=AsyncMock(return_value=generation),
        ),
        patch(
            "app.services.social_media_service.render_social_media_pngs",
            new=MagicMock(side_effect=RuntimeError("rendu impossible")),
        ),
    ):
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json()["raw_content"] == raw
    assert response.json()["html"] == html
    assert response.json()["images"] == []
    assert response.json()["render_error"] is not None


async def test_render_endpoint_passes_edited_html_exactly(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="render")
    message_id = await _add_exchange(conversation_id)
    edited = "  <!doctype html>\n<body><p>HTML édité</p></body>  "
    png = b"png"

    with patch(
        "app.services.social_media_service.render_social_media_pngs",
        new=MagicMock(
            return_value=[RenderedMediaImage(filename="aoria-media-01.png", content=png)]
        ),
    ) as render:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media/render",
            headers=auth_header(admin_user["token"]),
            json={"html": edited},
        )

    assert response.status_code == 200, response.text
    render.assert_called_once_with(edited)
    assert response.json()["images"][0]["content_base64"] == base64.b64encode(png).decode("ascii")


async def test_pdf_endpoint_exports_the_exact_edited_html(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="pdf")
    message_id = await _add_exchange(conversation_id)
    edited = "  <!doctype html>\n<body><p>PDF édité</p></body>  "
    pdf = b"%PDF-1.7\ncontenu"

    with patch(
        "app.services.social_media_service.render_social_media_pdf",
        new=MagicMock(return_value=pdf),
    ) as render:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media/pdf",
            headers=auth_header(admin_user["token"]),
            json={"html": edited},
        )

    assert response.status_code == 200, response.text
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"
    assert "aoria-media-linkedin.pdf" in response.headers["content-disposition"]
    render.assert_called_once_with(edited)


async def test_admin_cannot_generate_from_another_users_conversation(
    client: AsyncClient,
    admin_user: dict,
    manager_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, manager_user, suffix="client")
    message_id = await _add_exchange(conversation_id)

    with patch(
        "app.services.social_media_service.generate_social_media",
        new=AsyncMock(),
    ) as generate:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 403
    generate.assert_not_awaited()


async def test_security_response_never_reaches_social_media_llm(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(client, admin_user, suffix="security")
    message_id = await _add_exchange(
        conversation_id,
        rag_trace={"security_event": EVENT_TECHNICAL_RECON},
    )

    with patch(
        "app.services.social_media_service.generate_social_media",
        new=AsyncMock(),
    ) as generate:
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 422
    generate.assert_not_awaited()
