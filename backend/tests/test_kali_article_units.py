from dataclasses import replace

from app.rag.article_chunker import ArticleChunker
from app.rag.parent_expansion import deduplicate_article_passages
from app.rag.search import SearchResult
from app.services.kali_service import KaliService


def test_short_kali_articles_are_separate_and_metadata_is_preserved():
    articles = [
        dict(
            num=str(i),
            content=body,
            article_id=f"KALIARTI{i}",
            article_title=title,
            etat="VIGUEUR_NON_ETEN",
            date_debut="2001-05-01",
            date_fin="",
            section="Annexe",
            instrument_id="KALITEXT1",
            instrument_title="Cadres",
            instrument_status="VIGUEUR_NON_ETEN",
        )
        for i, title, body in [
            (5, "Période d'essai", "La période d'essai est fixée à 6 mois."),
            (6, "Congé de maladie", "Maintien du salaire pendant six mois."),
        ]
    ]
    text = KaliService._format_instrumented_articles(articles, "# CCN")
    chunks = ArticleChunker().chunk_with_meta(text)
    assert len(chunks) == 2
    for chunk, article in zip(chunks, articles, strict=True):
        assert chunk.article_nums == [article["num"]]
        assert chunk.article_id == article["article_id"]
        assert chunk.article_title == article["article_title"]
        assert chunk.article_effective_from == "2001-05-01"
        assert chunk.article_status == "VIGUEUR_NON_ETEN"
        assert article["content"] in chunk.text


def test_long_article_keeps_identity_and_title_on_all_fragments():
    text = KaliService._format_instrumented_articles(
        [
            dict(
                num="5",
                content="\n\n".join(
                    f"{i}° Disposition relative aux fonctions exercées et aux horaires de travail."
                    for i in range(30)
                ),
                article_id="KALIARTI5",
                article_title="Horaires",
                instrument_id="KALITEXT1",
                instrument_title="Cadres",
            )
        ],
        "# CCN",
    )
    chunks = ArticleChunker(chunk_size=150).chunk_with_meta(text)
    assert len(chunks) > 1
    assert all(c.article_id == "KALIARTI5" and c.article_title == "Horaires" for c in chunks)
    assert all("Horaires" in c.text for c in chunks)
    for i in range(30):
        assert any(
            f"{i}° Disposition relative aux fonctions exercées et aux horaires de travail."
            in chunk.text
            for chunk in chunks
        )


def test_dedup_requires_same_identity_scope_version_and_exact_passage():
    r = SearchResult(
        "body",
        "doc",
        "a",
        "ccn",
        1,
        1,
        0,
        0.5,
        organisation_id="org",
        article_id="KALIARTI5",
        instrument_id="KALITEXT1",
        article_effective_from="2001-05-01",
    )
    duplicate = replace(r, document_id="b")
    distinct = [
        replace(duplicate, organisation_id="other"),
        replace(duplicate, article_effective_from="2025-01-01"),
        replace(duplicate, text="other fragment"),
        replace(duplicate, article_id=None),
    ]
    assert deduplicate_article_passages([r, duplicate, *distinct]) == [r, *distinct]
