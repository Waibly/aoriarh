"""Tests des fonctions pures du service de fiche pratique.

On teste le parsing du JSON LLM, la conversion des tableaux markdown, le rendu
HTML et la règle d'éligibilité — sans dépendre de WeasyPrint (libs natives) ni
d'un appel réseau OpenAI.
"""

from datetime import datetime

from app.services.fiche_service import (
    FICHE_SYSTEM_PROMPT,
    FicheContent,
    _format_source,
    _md_table_to_html,
    fiche_filename,
    parse_fiche_content,
    render_fiche_html,
    select_fiche_references,
)

GEN_AT = datetime(2026, 6, 15, 10, 30)


def _content(**overrides) -> FicheContent:
    base = dict(
        eligible=True,
        titre="Préavis de démission",
        essentiel="Le préavis dépend de l'ancienneté et de la convention collective.",
        points_cles=["Aucun préavis légal général", "Découle de la CCN"],
        tableaux_markdown=[],
        exceptions=[],
        etapes=[],
    )
    base.update(overrides)
    return FicheContent(**base)


# --- parse_fiche_content --------------------------------------------------


def test_parse_minimal_json():
    raw = (
        '{"eligible": true, "titre": "Test", "essentiel": "Une phrase.", '
        '"points_cles": ["a", "b"]}'
    )
    content = parse_fiche_content(raw)
    assert content.eligible is True
    assert content.titre == "Test"
    assert content.points_cles == ["a", "b"]
    # Champs absents → listes vides, pas d'erreur.
    assert content.tableaux_markdown == []
    assert content.exceptions == []


def test_parse_filters_empty_list_items():
    raw = '{"titre": "T", "points_cles": ["a", "", "  ", "b"]}'
    content = parse_fiche_content(raw)
    assert content.points_cles == ["a", "b"]


def test_parse_eligible_false():
    content = parse_fiche_content('{"eligible": false, "titre": "X"}')
    assert content.eligible is False


def test_parse_html_keeps_raw_generation_unchanged():
    raw = (
        '<article class="fiche-content"><h1>Procédure disciplinaire</h1>'
        '<section class="procedure"><h2>Étapes</h2><ol>'
        + "".join(f"<li>Étape {index}</li>" for index in range(1, 11))
        + "</ol></section></article>"
    )
    content = parse_fiche_content(raw)
    assert content.body_html == raw
    assert content.titre == "Procédure disciplinaire"
    assert content.body_html.count("<li>") == 10
    assert content.warnings == []


def test_prompt_forbids_arbitrary_step_limit():
    assert "10 étapes utiles conserve" in FICHE_SYSTEM_PROMPT
    assert "aucune limite arbitraire" in FICHE_SYSTEM_PROMPT


def test_prompt_requires_highlighted_direct_answer_and_targeted_bold():
    assert 'Immédiatement après le <h1>' in FICHE_SYSTEM_PROMPT
    assert '<aside class="essential"><p>...</p></aside>' in FICHE_SYSTEM_PROMPT
    assert "Utilise <strong> avec parcimonie" in FICHE_SYSTEM_PROMPT
    assert "paragraphe entier en gras" in FICHE_SYSTEM_PROMPT


def test_inspection_warns_without_rewriting_unsupported_html():
    raw = '<article class="fiche-content"><h1>Titre</h1><img src="https://example.com/x"></article>'
    content = parse_fiche_content(raw)
    assert content.body_html == raw
    assert "balise <img> non prévue" in content.warnings
    assert "attribut src non prévu" in content.warnings


# --- _md_table_to_html ----------------------------------------------------


def test_markdown_table_conversion():
    md = "| Ancienneté | Préavis |\n|---|---|\n| < 2 ans | 1 mois |\n| >= 2 ans | 3 mois |"
    html = _md_table_to_html(md)
    assert "<table>" in html
    assert "<th>Ancienneté</th>" in html
    assert "<td>1 mois</td>" in html
    assert html.count("<tr>") == 3  # entête + 2 lignes


def test_markdown_table_rejects_non_table():
    assert _md_table_to_html("juste du texte") == ""
    assert _md_table_to_html("| une seule ligne |") == ""


def test_markdown_table_preserves_bold():
    md = "| Col |\n|---|\n| **1 mois** |"
    html = _md_table_to_html(md)
    assert "<strong>1 mois</strong>" in html


# --- _format_source -------------------------------------------------------


def test_format_source_with_articles():
    src = {
        "source_type_label": "Code du travail",
        "article_nums": ["L.1237-1", "L.1234-1"],
    }
    line = _format_source(src)
    assert "Code du travail" in line
    assert "art. L.1237-1, L.1234-1" in line


def test_format_source_jurisprudence_with_date():
    src = {
        "source_type_label": "Cass. soc.",
        "numero_pourvoi": "21-12.345",
        "date_decision": "2023-05-10",
    }
    line = _format_source(src)
    assert "Cass. soc." in line
    assert "n° 21-12.345" in line
    assert "10/05/2023" in line


def test_select_fiche_references_keeps_only_cited_legal_foundations():
    sources = [
        {
            "source_type": "code_travail",
            "source_type_label": "Code du travail",
            "document_name": "Code du travail",
            "article_nums": ["L.2421-3", "R.2421-10"],
        },
        {
            "source_type": "arret_cour_cassation",
            "source_type_label": "Arrêt Cour de cassation",
            "document_name": "Décision 21-12.345",
            "numero_pourvoi": "21-12.345",
            "date_decision": "2023-05-10",
        },
        {
            "source_type": "arret_cour_cassation",
            "source_type_label": "Arrêt Cour de cassation",
            "document_name": "Décision 22-99.999",
            "numero_pourvoi": "22-99.999",
        },
    ]

    selected = select_fiche_references(
        "La consultation est requise (C. trav., art. L. 2421-3). "
        "La Cour de cassation le confirme (Cass. soc., 10 mai 2023, n° 21-12.345).",
        sources,
    )

    assert len(selected) == 2
    assert selected[0]["article_nums"] == ["L.2421-3"]
    assert selected[1]["numero_pourvoi"] == "21-12.345"


def test_select_fiche_references_omits_uncited_sources_without_identifiers():
    sources = [
        {
            "source_type": "reglement_interieur",
            "source_type_label": "Règlement intérieur",
            "document_name": "Règlement intérieur ACME",
        }
    ]

    assert select_fiche_references("Le Code du travail fixe la règle.", sources) == []


# --- render_fiche_html ----------------------------------------------------


def test_render_html_contains_charte_and_blocks():
    html = render_fiche_html(_content(), [], generated_at=GEN_AT)
    assert "AORIA RH" in html
    assert "#652BB0" in html  # violet de la charte
    assert "Préavis de démission" in html
    assert "Points clés" in html
    # La date décrit honnêtement la génération du contenu.
    assert "Contenu généré le 15/06/2026" in html
    assert "À jour au" not in html


def test_render_html_places_clickable_website_at_footer_bottom_right():
    html = render_fiche_html(_content(), [], generated_at=GEN_AT)
    assert '<a class="site-link" href="https://aoriarh.fr">aoriarh.fr</a>' in html
    assert "position:absolute; right:0; bottom:2px" in html
    assert ".footer .site-link" in html


def test_render_html_uses_compact_single_line_header():
    html = render_fiche_html(_content(), [], generated_at=GEN_AT)
    assert 'class="logo"' in html
    assert "grid-template-columns:1fr auto 1fr" in html
    assert ".header .tag { grid-column:2" in html


def test_render_html_balances_exceptions_vertical_spacing():
    html = render_fiche_html(
        _content(exceptions=["Vérifier la convention collective."]),
        [],
        generated_at=GEN_AT,
    )
    assert "padding:12px 16px" in html
    assert ".exceptions strong { display:flex" in html
    assert ".exceptions li:last-child { margin-bottom:0; }" in html


def test_render_html_escapes_user_content():
    content = _content(titre="<script>alert(1)</script>")
    html = render_fiche_html(content, [], generated_at=GEN_AT)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_html_includes_sources_block():
    sources = [{"source_type_label": "Code du travail", "article_nums": ["L.1237-1"]}]
    html = render_fiche_html(_content(), sources, generated_at=GEN_AT)
    assert "Références juridiques" in html
    assert "L.1237-1" in html
    assert "document_id" not in html


def test_render_html_optional_blocks_omitted():
    html = render_fiche_html(_content(), [], generated_at=GEN_AT)
    # Pas d'exceptions ni d'étapes fournies → blocs absents.
    assert "À surveiller" not in html
    assert "Étapes" not in html


def test_render_html_renders_table_from_markdown():
    content = _content(tableaux_markdown=["| A | B |\n|---|---|\n| 1 | 2 |"])
    html = render_fiche_html(content, [], generated_at=GEN_AT)
    assert "<table>" in html
    assert "<td>1</td>" in html


def test_render_html_inserts_dynamic_body_verbatim():
    raw = (
        '<article class="fiche-content"><h1>Une procédure</h1>'
        '<section class="procedure"><h2>Étapes</h2><ol>'
        '<li>Première</li><li>Deuxième</li></ol></section></article>'
    )
    content = parse_fiche_content(raw)
    final_html = render_fiche_html(content, [], generated_at=GEN_AT)
    assert raw in final_html
    assert "Première" in final_html
    assert "counter-reset:fiche-step" in final_html


def test_render_html_highlights_direct_answer_in_violet():
    raw = (
        '<article class="fiche-content"><h1>Une réponse</h1>'
        '<aside class="essential"><p><strong>Oui.</strong> La règle s’applique.</p></aside>'
        "</article>"
    )
    final_html = render_fiche_html(parse_fiche_content(raw), [], generated_at=GEN_AT)
    assert "background:#f5f3ff; color:#652BB0" in final_html
    assert "border-left:5px solid #652BB0" in final_html
    assert ".essential strong, .essentiel strong { color:#652BB0; font-weight:800; }" in final_html


def test_render_html_shows_warning_next_to_unmodified_generation():
    raw = '<article class="fiche-content"><h1>Titre</h1><img src="x"></article>'
    content = parse_fiche_content(raw)
    final_html = render_fiche_html(content, [], generated_at=GEN_AT)
    assert raw in final_html
    assert "Avertissement de mise en page" in final_html
    assert "balise &lt;img&gt; non prévue" in final_html


def test_filename_preserves_accented_words_as_ascii():
    content = FicheContent(titre="Récupération d’un trop-perçu")
    assert fiche_filename(content) == "fiche-recuperation-d-un-trop-percu.pdf"
