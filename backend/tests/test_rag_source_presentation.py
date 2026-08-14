from unittest.mock import patch

from app.rag.agent import RAGAgent
from app.rag.search import SearchResult


def test_formatted_source_exposes_reliable_presentation_metadata():
    result = SearchResult(
        text="Article 12 — Le délai applicable est de deux mois.",
        seed_text="Le délai applicable est de deux mois.",
        doc_name="CCN Exemple (IDCC 1234)",
        document_id="doc-1",
        source_type="convention_collective_nationale",
        norme_niveau=6,
        norme_poids=0.7,
        chunk_index=0,
        score=0.9,
        content_date="2026-06-01",
        idcc="1234",
        article_nums=["12"],
        section_path="Préavis",
    )

    with patch("app.rag.agent._search_engine"), patch(
        "app.rag.agent.get_reranker"
    ):
        source = RAGAgent().format_sources([result])[0]

    assert source.content_date == "2026-06-01"
    assert source.idcc == "1234"
    assert source.legal_status is None
    assert source.corpus_status == "available_at_answer_time"
    assert source.excerpt == "Le délai applicable est de deux mois."
