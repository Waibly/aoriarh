import json

import pytest

from app.rag.article_chunker import ARTICLE_METADATA_PREFIX, ArticleChunker
from app.rag.text_cleaner import clean_text
from app.services.kali_service import KaliService


@pytest.mark.parametrize("title", [
    "Structure “Salarié + enfant(s)/Conjoint facultatif”",
    'Formation initiale et continue. ― Formation complémentaire "passerelle”',
    "L’emploi — temps  partiel\u00a0et\u200b garanties",
])
def test_cleaning_preserves_kali_json_and_chunk_metadata(title):
    text = KaliService._format_instrumented_articles([
        dict(num="5", article_id="KALIARTI5", article_title=title,
             instrument_id="KALITEXT1", instrument_title="Prévoyance",
             content="Le salarié bénéficie des garanties prévues par le présent accord. " * 4),
    ], "# CCN")
    cleaned = clean_text(text)
    original = next(line for line in text.splitlines() if line.startswith(ARTICLE_METADATA_PREFIX))
    assert original in cleaned.splitlines()
    chunks = ArticleChunker().chunk_with_meta(cleaned)
    assert chunks
    assert all(chunk.article_title == title and chunk.article_id == "KALIARTI5" for chunk in chunks)


def test_metadata_boundary_is_preserved_before_lowercase_prose():
    metadata = ARTICLE_METADATA_PREFIX + json.dumps({"article_title": "“Titre”"}, ensure_ascii=False)
    cleaned = clean_text(f'“Introduction”\n{metadata}\nle salarié  bénéficie des garanties.\n')
    assert cleaned == f'"Introduction"\n{metadata}\nle salarié bénéficie des garanties.'


def test_invalid_metadata_is_not_repaired_or_hidden():
    invalid = ARTICLE_METADATA_PREFIX + '{"article_title": "Titre "invalide""}'
    text = f'### Article 5\n{invalid}\n\nLe salarié bénéficie des garanties de cet accord.\n'
    assert invalid in clean_text(text)
    with pytest.raises(json.JSONDecodeError):
        ArticleChunker().chunk_with_meta(clean_text(text))


def test_prose_cleaning_still_removes_page_numbers_and_normalizes_typography():
    assert clean_text('  “Texte”  —  suite\nPage 1 sur 3\n\n') == '"Texte" - suite'
