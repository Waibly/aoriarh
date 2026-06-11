"""Tests for the relevance floor (step 3.6) that cuts low-scored groups."""
from __future__ import annotations

import app.rag.config as rag_config
from app.rag.agent import RAGAgent
from app.rag.search import SearchResult


def _mk(score: float, doc_id: str = "doc", source_type: str = "code_travail") -> SearchResult:
    return SearchResult(
        text="x",
        doc_name=f"Doc {doc_id}",
        document_id=doc_id,
        source_type=source_type,
        norme_niveau=3,
        norme_poids=1.0,
        chunk_index=0,
        score=score,
    )


class TestApplyScoreFloor:
    def test_empty_input(self):
        kept, dropped = RAGAgent._apply_score_floor([])
        assert kept == [] and dropped == []

    def test_cuts_below_floor(self):
        results = [_mk(0.9, "a"), _mk(0.7, "b"), _mk(0.5, "c"), _mk(0.6, "d"),
                   _mk(0.2, "e"), _mk(0.31, "f")]
        kept, dropped = RAGAgent._apply_score_floor(results)
        assert [r.document_id for r in kept] == ["a", "b", "d", "c"]
        assert {r.document_id for r in dropped} == {"e", "f"}
        assert all(r.score >= rag_config.SOURCE_SCORE_FLOOR for r in kept)

    def test_min_keep_guard_on_weak_retrieval(self):
        """Even if everything is under the floor, the best N survive."""
        results = [_mk(0.30, "a"), _mk(0.20, "b"), _mk(0.10, "c"), _mk(0.05, "d")]
        kept, dropped = RAGAgent._apply_score_floor(results)
        assert len(kept) == rag_config.SOURCE_FLOOR_MIN_KEEP
        assert [r.document_id for r in kept] == ["a", "b", "c"]
        assert [r.document_id for r in dropped] == ["d"]

    def test_all_above_floor_keeps_everything(self):
        results = [_mk(0.8, str(i)) for i in range(10)]
        kept, dropped = RAGAgent._apply_score_floor(results)
        assert len(kept) == 10 and dropped == []

    def test_output_sorted_descending(self):
        results = [_mk(0.4, "low"), _mk(0.9, "high"), _mk(0.6, "mid")]
        kept, _ = RAGAgent._apply_score_floor(results)
        assert [r.score for r in kept] == sorted(
            (r.score for r in kept), reverse=True,
        )
