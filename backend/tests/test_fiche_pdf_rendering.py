"""Contrôle du vrai moteur PDF pour les corps de longueur variable."""

from datetime import datetime

import fitz

from app.services.fiche_service import parse_fiche_content, render_fiche_pdf


def test_long_procedure_keeps_every_step_without_footer_only_page():
    steps = "".join(
        f"<li>Étape {index} — effectuer le contrôle, documenter le résultat "
        "et conserver le justificatif correspondant.</li>"
        for index in range(1, 31)
    )
    fragment = (
        '<article class="fiche-content"><h1>Procédure longue</h1>'
        '<section class="procedure"><h2>Étapes</h2>'
        f"<ol>{steps}</ol></section></article>"
    )

    pdf = render_fiche_pdf(
        parse_fiche_content(fragment),
        [],
        generated_at=datetime(2026, 8, 25),
    )
    document = fitz.open(stream=pdf, filetype="pdf")
    page_texts = [page.get_text() for page in document]

    assert len(page_texts) == 2
    assert sum(text.count("Étape ") for text in page_texts) == 30
    assert all("Contenu généré le 25/08/2026" in text for text in page_texts)
    assert "1/2" in page_texts[0]
    assert "2/2" in page_texts[1]
    assert all(len(text) > 500 for text in page_texts)


def test_external_resource_is_ignored_without_hiding_generation():
    fragment = (
        '<article class="fiche-content"><h1>Contenu brut</h1>'
        '<p>Le texte doit rester visible.</p>'
        '<img src="https://invalid.example/image.png"></article>'
    )

    pdf = render_fiche_pdf(
        parse_fiche_content(fragment),
        [],
        generated_at=datetime(2026, 8, 25),
    )
    document = fitz.open(stream=pdf, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)

    assert "Le texte doit rester visible." in text
    assert "Avertissement de mise en page" in text
    assert "balise <img> non prévue" in text


def test_legal_reference_and_its_topic_stay_on_the_same_page():
    filler = "".join(
        f"<p>Paragraphe {index} : contrôle détaillé du dossier et conservation "
        "des justificatifs nécessaires pour sécuriser la procédure.</p>"
        for index in range(26)
    )
    fragment = (
        '<article class="fiche-content"><h1>Documents de fin de contrat</h1>'
        f"<section><h2>Règles</h2>{filler}</section>"
        '<section class="legal-references"><h2>Références juridiques</h2><ul>'
        '<li><strong>Cour de cassation, 03/09/2025, n° 24-16.546</strong>'
        '<span class="reference-topic">Remise des documents de fin de contrat</span></li>'
        '<li><strong>Code du travail, art. L1234-19</strong>'
        '<span class="reference-topic">Délivrance du certificat de travail</span></li>'
        "</ul></section></article>"
    )

    pdf = render_fiche_pdf(
        parse_fiche_content(fragment),
        [],
        generated_at=datetime(2026, 8, 25),
    )
    document = fitz.open(stream=pdf, filetype="pdf")
    page_texts = [page.get_text() for page in document]

    assert len(page_texts) == 2
    assert "24-16.546" in page_texts[0]
    assert "Remise des documents de fin de contrat" in page_texts[0]
    assert "L1234-19" in page_texts[1]
    assert "Délivrance du certificat de travail" in page_texts[1]


def test_footer_contains_clickable_aoria_website_link():
    fragment = (
        '<article class="fiche-content"><h1>Une fiche</h1>'
        '<aside class="essential"><p>La réponse directe.</p></aside></article>'
    )
    pdf = render_fiche_pdf(
        parse_fiche_content(fragment),
        [],
        generated_at=datetime(2026, 8, 25),
    )
    document = fitz.open(stream=pdf, filetype="pdf")

    links = [link.get("uri") for page in document for link in page.get_links()]
    assert "https://aoriarh.fr" in links
    assert "aoriarh.fr" in document[0].get_text()
    site_bounds = document[0].search_for("aoriarh.fr")[0]
    page_number_bounds = document[0].search_for("1/1")[0]
    assert page_number_bounds.y0 > site_bounds.y1
    assert abs(page_number_bounds.x1 - site_bounds.x1) < 3
