"""Tests du générateur HTML social et de son rendu déterministe."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from app.services.social_media_service import (
    SOCIAL_MEDIA_SYSTEM_PROMPT,
    build_social_media_reference_context,
    build_social_media_user_prompt,
    generate_social_media,
    inspect_social_media_fragment,
    render_social_media_document,
    render_social_media_pngs,
)

RAW_FRAGMENT = """<main class="carousel">
  <section class="slide slide-cover">
    <p class="eyebrow">Droit social</p>
    <h1>Question courte, réponse utile</h1>
  </section>
  <section class="slide slide-steps">
    <h2>Les étapes adaptées au sujet</h2>
    <ol class="steps"><li>Vérifier</li><li>Agir</li></ol>
  </section>
</main>"""


def _response(content: str):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def test_user_prompt_delimits_source_data_without_rewriting_it():
    prompt = build_social_media_user_prompt(
        question="  Question conservée ?  ",
        answer_markdown="Réponse\navec sa mise en forme.",
        references=["Code du travail, art. L.1234-1"],
        user_profile="drh",
    )

    assert "<question_source>\n  Question conservée ?  \n</question_source>" in prompt
    assert "<reponse_source>\nRéponse\navec sa mise en forme.\n</reponse_source>" in prompt
    assert "- Code du travail, art. L.1234-1" in prompt


def test_inspection_only_adds_warnings_and_never_changes_raw_fragment():
    raw = "  <p>Sortie libre non conforme</p>  "
    warnings = inspect_social_media_fragment(raw, [])

    assert raw == "  <p>Sortie libre non conforme</p>  "
    assert any("main.carousel" in warning for warning in warnings)
    assert any("section.slide" in warning for warning in warnings)


def test_prompt_requires_sober_copy_and_explained_legal_references():
    assert "N'emploie aucun superlatif" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "adverbe d'intensité ou de surenchère" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert '<span class="reference-topic">' in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "son bloc explicatif suffit" in SOCIAL_MEDIA_SYSTEM_PROMPT


def test_reference_context_exposes_the_topic_without_changing_the_exact_label():
    context = build_social_media_reference_context(
        [
            {
                "source_type_label": "Code du travail",
                "article_nums": ["L. 1234-1"],
                "section_path": "Rupture du contrat > Préavis",
                "excerpt": "Le préavis dépend des règles applicables.",
            }
        ]
    )
    prompt = build_social_media_user_prompt(
        question="Question",
        answer_markdown="Réponse",
        references=["Code du travail, art. L. 1234-1"],
        user_profile="drh",
        reference_context=context,
    )

    assert "Référence autorisée : Code du travail, art. L. 1234-1" in prompt
    assert "Rubrique documentaire : Rupture du contrat > Préavis" in prompt
    assert "Extrait de contexte : Le préavis dépend" in prompt
    assert "<contexte_references_pour_les_objets>" in prompt


@pytest.mark.asyncio
async def test_generation_returns_exact_non_empty_llm_output_without_fallback():
    raw = f"  {RAW_FRAGMENT}\n"
    create = AsyncMock(return_value=_response(raw))

    with patch(
        "app.services.social_media_service._llm.chat.completions.create",
        create,
    ):
        generation = await generate_social_media(
            question="Question",
            answer_markdown="Réponse",
            sources=[],
            generated_at=datetime(2026, 9, 1),
        )

    assert generation.raw_content == raw
    assert raw in generation.html
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_empty_generation_fails_after_one_call_without_substitute():
    create = AsyncMock(return_value=_response(""))

    with (
        patch(
            "app.services.social_media_service._llm.chat.completions.create",
            create,
        ),
        pytest.raises(RuntimeError, match="sortie vide"),
    ):
        await generate_social_media(
            question="Question",
            answer_markdown="Réponse",
            sources=[],
        )

    assert create.await_count == 1


def test_renderer_creates_one_exact_size_png_per_slide():
    html = render_social_media_document(
        RAW_FRAGMENT,
        generated_at=datetime(2026, 9, 1),
    )

    images = render_social_media_pngs(html)

    assert [image.filename for image in images] == [
        "aoria-media-01.png",
        "aoria-media-02.png",
    ]
    for image in images:
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
        pixmap = fitz.Pixmap(image.content)
        assert (pixmap.width, pixmap.height) == (1080, 1350)


def test_document_anchors_logo_and_footer_at_the_bottom_of_each_slide():
    html = render_social_media_document(
        RAW_FRAGMENT,
        generated_at=datetime(2026, 9, 1),
    )

    assert "width:1080px; height:1350px" in html
    assert "left:82px; bottom:50px; width:190px" in html
    assert "right:82px; bottom:48px; border-top" in html
    assert ".reference-topic { display:block" in html
