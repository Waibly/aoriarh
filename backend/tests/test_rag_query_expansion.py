"""Tests de fusion conservés après retrait de l’ancienne expansion LLM."""

from app.rag.agent import RAGAgent
from app.rag.search import SearchResult


def _make_result(
    text: str, score: float, doc_id: str = "doc1", chunk: int = 0,
) -> SearchResult:
    return SearchResult(
        text=text,
        doc_name="test.pdf",
        document_id=doc_id,
        source_type="code_travail",
        norme_niveau=4,
        norme_poids=0.8,
        chunk_index=chunk,
        score=score,
    )


class TestReciprocalRankFusion:
    def test_basic_fusion(self):
        list1 = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("B", 0.8, "doc2", 0),
        ]
        list2 = [
            _make_result("B", 0.7, "doc2", 0),
            _make_result("C", 0.6, "doc3", 0),
        ]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # B appears in both lists → higher RRF score
        assert fused[0].document_id == "doc2"  # B appears in both → highest score
        assert len(fused) == 3  # A, B, C deduplicated

    def test_deduplication_by_doc_chunk(self):
        list1 = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("A copy", 0.8, "doc1", 0),  # same doc_id + chunk
        ]
        list2 = [
            _make_result("A again", 0.7, "doc1", 0),  # same doc_id + chunk
        ]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # All have same (doc1, 0) key → only 1 result
        assert len(fused) == 1

    def test_empty_lists(self):
        fused = RAGAgent._reciprocal_rank_fusion([[], []], k=60)
        assert fused == []

    def test_single_list(self):
        results = [
            _make_result("A", 0.9, "doc1", 0),
            _make_result("B", 0.8, "doc2", 0),
        ]
        fused = RAGAgent._reciprocal_rank_fusion([results], k=60)
        assert len(fused) == 2

    def test_rrf_scores_correct(self):
        list1 = [_make_result("A", 0.9, "doc1", 0)]
        list2 = [_make_result("A", 0.7, "doc1", 0)]

        fused = RAGAgent._reciprocal_rank_fusion([list1, list2], k=60)

        # A is rank 0 in both lists: score = 1/(60+0+1) + 1/(60+0+1) = 2/61
        expected = 2.0 / 61.0
        assert abs(fused[0].score - expected) < 1e-10
