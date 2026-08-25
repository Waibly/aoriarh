"""Tests des fonctions pures du service de fiche pratique.

On teste le parsing du JSON LLM, la conversion des tableaux markdown, le rendu
HTML et la règle d'éligibilité — sans dépendre de WeasyPrint (libs natives) ni
d'un appel réseau OpenAI.
"""

from datetime import datetime

from app.services.fiche_service import (
    FicheContent,
    _format_source,
    _md_table_to_html,
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
    raw = '{"eligible": true, "titre": "Test", "essentiel": "Une phrase.", "points_cles": ["a", "b"]}'
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
    # Mention de validité avec la date de génération.
    assert "À jour au 15/06/2026" in html


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
