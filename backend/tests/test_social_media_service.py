"""Tests du générateur HTML social et de son rendu déterministe."""

import base64
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import fitz
import pytest

from app.services.social_media_service import (
    LINKEDIN_CAROUSEL_SYSTEM_PROMPT,
    SOCIAL_MEDIA_SYSTEM_PROMPT,
    _load_logo_data_url,
    build_social_media_reference_context,
    build_social_media_user_prompt,
    generate_social_media,
    inspect_social_media_fragment,
    render_social_media_document,
    render_social_media_pdf,
    render_social_media_pngs,
)

RAW_FRAGMENT = """<main class="carousel">
  <section class="slide slide-cover">
    <p class="eyebrow">Droit social</p>
    <h1>Question courte, réponse utile</h1>
    <div class="slide-body"><p class="lead">Une réponse fidèle.</p></div>
  </section>
  <section class="slide slide-steps">
    <h2>Les étapes adaptées au sujet</h2>
    <div class="slide-body">
      <ol class="steps"><li>Vérifier</li><li>Agir</li></ol>
    </div>
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


def test_inspection_warns_about_missing_slide_body_without_changing_output():
    raw = '<main class="carousel"><section class="slide"><h2>Titre</h2></section></main>'

    warnings = inspect_social_media_fragment(raw, [])

    assert any("exactement un bloc slide-body" in warning for warning in warnings)
    assert raw == '<main class="carousel"><section class="slide"><h2>Titre</h2></section></main>'


def test_prompt_requires_sober_copy_and_explained_legal_references():
    assert "carrousel Instagram" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert (
        "document PDF dans un post LinkedIn" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
    )
    assert "post d'accompagnement distinct" in LINKEDIN_CAROUSEL_SYSTEM_PROMPT
    assert "N'emploie aucun superlatif" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "adverbe d'intensité ou de surenchère" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert '<span class="reference-topic">' in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "exactement « Références juridiques »" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "N'écris jamais" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert (
        '<p class="source-note">Référence exacte</p>' in SOCIAL_MEDIA_SYSTEM_PROMPT
    )
    assert "sans attendre la dernière slide" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "première slide est l'ouverture visuelle" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "Aère verticalement" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert '<div class="slide-body">' in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "titre en haut et centre" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "La fidélité juridique prime toujours" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "Le français doit rester idiomatique" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "Ne fixe aucun nombre de mots arbitraire" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "slide-compact" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "slide-dense" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "répartis-le sur une slide supplémentaire" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "N'écris jamais <strong>Libellé</strong>Valeur" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "publication publique et décontextualisée" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "forme ou type de société" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "effectif exact ou" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "seuil abstrait" in SOCIAL_MEDIA_SYSTEM_PROMPT
    assert "N'en fais jamais un exemple" in SOCIAL_MEDIA_SYSTEM_PROMPT


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
async def test_linkedin_carousel_generation_uses_its_dedicated_prompt():
    create = AsyncMock(return_value=_response(RAW_FRAGMENT))

    with patch(
        "app.services.social_media_service._llm.chat.completions.create",
        create,
    ):
        await generate_social_media(
            question="Question",
            answer_markdown="Réponse",
            sources=[],
            linkedin_carousel=True,
        )

    assert create.await_args.kwargs["messages"][0] == {
        "role": "system",
        "content": LINKEDIN_CAROUSEL_SYSTEM_PROMPT,
    }


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


def test_renderer_creates_one_pdf_page_per_slide():
    html = render_social_media_document(
        RAW_FRAGMENT,
        generated_at=datetime(2026, 9, 1),
    )

    pdf = render_social_media_pdf(html)

    assert pdf.startswith(b"%PDF-")
    with fitz.open(stream=pdf, filetype="pdf") as document:
        assert document.page_count == 2
        assert document[0].rect.width / document[0].rect.height == pytest.approx(0.8)


def test_title_stays_high_while_legal_content_is_centered_above_footer():
    fragment = """<main class="carousel">
      <section class="slide slide-warning slide-compact">
        <h2>Un entretien distinct</h2>
        <div class="slide-body">
          <ul class="checklist">
            <li>Le retour après un temps partiel lié à la parentalité est concerné.</li>
            <li>L'obligation ne s'applique pas si l'entretien a déjà eu lieu.</li>
          </ul>
          <p class="source-note">Code du travail, art. L. 6315-1</p>
          <div class="warning">La situation doit être appréciée au regard des
          conditions prévues par le texte.</div>
        </div>
      </section>
    </main>"""
    html = render_social_media_document(fragment, generated_at=datetime(2026, 9, 4))

    with fitz.open(stream=render_social_media_pdf(html), filetype="pdf") as document:
        page = document[0]
        title = page.search_for("Un entretien distinct")[0]
        first_item = page.search_for("Le retour après un temps partiel")[0]
        warning = page.search_for("La situation doit être appréciée")[0]
        footer = page.search_for("aoriarh.fr")[0]

        assert title.y0 < 120
        assert first_item.y0 > title.y1 + 100
        assert warning.y1 < footer.y0 - 30


def test_document_anchors_logo_and_footer_at_the_bottom_of_each_slide():
    html = render_social_media_document(
        RAW_FRAGMENT,
        generated_at=datetime(2026, 9, 1),
    )

    assert "width:1080px; height:1350px" in html
    assert "flex-direction:column; justify-content:flex-start" in html
    assert "left:82px; bottom:40px; width:190px" in html
    assert "right:82px; bottom:40px; border-top" in html
    assert "padding-top:38px" in html
    assert ".slide:first-child { color:#fff" in html
    assert ".slide-body { flex:1; min-height:0; display:flex" in html
    assert "justify-content:center; gap:24px; padding-top:30px" in html
    assert ".slide-body > * { flex-shrink:0; }" in html
    assert "display:flex; min-height:112px" in html
    assert "position:relative; overflow:hidden; display:flex" not in html
    assert ".slide-compact .slide-body" in html
    assert ".slide-dense .slide-body" in html
    assert ".checklist li > strong:first-child" in html
    assert ".steps li > strong:first-child" in html
    assert "display:block; margin:0 0 9px" in html
    assert ".highlight::before { content:''; position:absolute" in html
    assert "border-radius:26px 0 0 26px; background:var(--violet)" in html
    assert "border-left:11px solid var(--violet)" not in html
    assert ".reference-topic { display:block" in html


def test_brand_logo_keeps_the_official_dark_and_violet_colors():
    data_url = _load_logo_data_url(white=False)
    svg = base64.b64decode(data_url.split(",", 1)[1]).decode("utf-8")

    assert "#313131" in svg
    assert "#652bb0" in svg.lower()
