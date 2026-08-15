"""KALI parent metadata needed to distinguish successive CCN agreements."""

from types import SimpleNamespace

from app.rag.article_chunker import ArticleChunker
from app.services.kali_service import KaliService


def test_kali_epoch_dates_are_normalised_and_open_end_is_omitted():
    assert KaliService._normalise_kali_date(1735689600000) == "2025-01-01"
    assert KaliService._normalise_kali_date(32472144000000) == ""


def test_formatted_kali_articles_round_trip_parent_metadata():
    ccn = SimpleNamespace(titre="Syntec", idcc="1486")
    articles = [
        {
            "num": "1er",
            "content": "Position 2.2, coefficient 130 : 2 850 euros.",
            "section": "Salaires minimaux",
            "instrument_id": "KALITEXT000050228699",
            "instrument_title": "Accord du 26 juin 2024 relatif aux salaires minimaux",
            "instrument_status": "VIGUEUR_ETEN",
            "date_debut": "2025-01-01",
            "date_fin": "",
        }
    ]

    markdown = KaliService._format_articles_as_markdown(articles, ccn)
    chunks = ArticleChunker().chunk_with_meta(markdown)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.instrument_id == "KALITEXT000050228699"
    assert chunk.instrument_title.startswith("Accord du 26 juin 2024")
    assert chunk.effective_from == "2025-01-01"
    assert chunk.instrument_status == "VIGUEUR_ETEN"
    assert chunk.section_path == "Salaires minimaux"


def test_generated_kali_document_detection_excludes_bocc_documents():
    generated_ccn = SimpleNamespace(
        name="CCN Syntec (IDCC 1486)",
        source_type="convention_collective_nationale",
    )
    generated_accords = SimpleNamespace(
        name="Accords de branche — Syntec (IDCC 1486)",
        source_type="accord_branche",
    )
    bocc = SimpleNamespace(
        name="Avenant du 12 mars 2026 (IDCC 1486)",
        source_type="convention_collective_nationale",
    )

    assert KaliService._is_generated_kali_document(generated_ccn) is True
    assert KaliService._is_generated_kali_document(generated_accords) is True
    assert KaliService._is_generated_kali_document(bocc) is False
