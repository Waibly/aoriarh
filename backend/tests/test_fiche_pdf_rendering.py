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
