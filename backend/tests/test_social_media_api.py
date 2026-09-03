"""Tests d'accès et de fidélité des endpoints de média social."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.models.conversation import Message
from app.services.linkedin_post_service import LinkedInPostGeneration
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


async def test_admin_receives_post_then_exact_carousel_without_eager_png_render(
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
    post_content = "  Post court complémentaire.\n\nVotre pratique ?  "
    post_generation = LinkedInPostGeneration(
        content=post_content,
        references=[],
        warnings=["Avertissement post visible"],
    )

    with (
        patch(
            "app.services.social_media_service.generate_social_media",
            new=AsyncMock(return_value=generation),
        ) as generate,
        patch(
            "app.services.linkedin_post_service.generate_linkedin_carousel_post",
            new=AsyncMock(return_value=post_generation),
        ) as generate_post,
    ):
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media?include_post=true",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "post": {
            "content": post_content,
            "character_count": len(post_content),
            "references": [],
            "warnings": ["Avertissement post visible"],
        },
        "post_error": None,
        "raw_content": raw,
        "html": html,
        "images": [],
        "references": [],
        "warnings": ["Avertissement visible"],
        "render_error": None,
    }
    assert generate.await_args.kwargs["question"] == "Quelle procédure appliquer ?"
    assert generate.await_args.kwargs["answer_markdown"] == "Voici la procédure à appliquer."
    assert generate.await_args.kwargs["linkedin_carousel"] is True
    assert generate_post.await_args.kwargs["carousel_content"] == raw
    assert generate_post.await_args.kwargs["answer_markdown"] == (
        "Voici la procédure à appliquer."
    )


async def test_post_failure_keeps_non_empty_carousel_output_visible(
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
            "app.services.linkedin_post_service.generate_linkedin_carousel_post",
            new=AsyncMock(side_effect=RuntimeError("post impossible")),
        ),
    ):
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media?include_post=true",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json()["raw_content"] == raw
    assert response.json()["html"] == html
    assert response.json()["images"] == []
    assert response.json()["post"] is None
    assert response.json()["post_error"] is not None
    assert response.json()["render_error"] is None


async def test_standalone_media_does_not_generate_a_linkedin_post(
    client: AsyncClient,
    admin_user: dict,
) -> None:
    conversation_id = await _create_conversation(
        client, admin_user, suffix="media-only"
    )
    message_id = await _add_exchange(conversation_id)
    raw = '<main class="carousel"><section class="slide">Média</section></main>'
    generation = SocialMediaGeneration(
        raw_content=raw,
        html=f"<!doctype html><body>{raw}</body>",
        references=[],
        warnings=[],
    )

    with (
        patch(
            "app.services.social_media_service.generate_social_media",
            new=AsyncMock(return_value=generation),
        ) as generate,
        patch(
            "app.services.linkedin_post_service.generate_linkedin_carousel_post",
            new=AsyncMock(),
        ) as generate_post,
    ):
        response = await client.post(
            f"/api/v1/conversations/messages/{message_id}/social-media",
            headers=auth_header(admin_user["token"]),
        )

    assert response.status_code == 200, response.text
    assert response.json()["post"] is None
    assert response.json()["post_error"] is None
    assert generate.await_args.kwargs["linkedin_carousel"] is False
    generate_post.assert_not_awaited()


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
