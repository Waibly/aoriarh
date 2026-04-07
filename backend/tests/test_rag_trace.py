"""Tests for the RagTrace dataclass and serialization helpers."""
from __future__ import annotations

from app.rag.agent import RagTrace, _serialize_chunks
from app.rag.search import SearchResult


def _mk(text: str = "", chunk_idx: int = 0, score: float = 0.5,
        doc_id: str = "doc-1") -> SearchResult:
    return SearchResult(
        text=text,
        doc_name="My Doc",
        document_id=doc_id,
        source_type="code_travail",
        norme_niveau=1,
        norme_poids=1.0,
        chunk_index=chunk_idx,
        score=score,
    )


class TestRagTrace:
    def test_default_construction(self):
        t = RagTrace(query_original="hello")
        assert t.query_original == "hello"
        assert t.query_condensed is None
        assert t.variants == []
        assert t.identifiers_detected == {}
        assert t.boost_injected == 0
        assert t.hybrid_results == []
        assert t.rerank_results == []
        assert t.parent_groups == []
        assert t.perf_ms == {}
        assert t.out_of_scope is False
        assert t.no_results is False
        assert t.error is None

    def test_to_dict_serializable(self):
        import json
        t = RagTrace(
            query_original="q",
            query_condensed="qc",
            variants=["v1", "v2"],
            perf_ms={"total": 1234.5},
            model="gpt-5-mini",
            out_of_scope=True,
        )
        d = t.to_dict()
        # Must be JSON-serializable
        s = json.dumps(d)
        assert "v1" in s
        assert d["query_condensed"] == "qc"
        assert d["out_of_scope"] is True
        assert d["perf_ms"]["total"] == 1234.5


class TestSerializeChunks:
    def test_empty_list(self):
        assert _serialize_chunks([]) == []

    def test_basic_serialization(self):
        chunks = [_mk(text="A long text content " * 30, chunk_idx=0, score=0.9)]
        out = _serialize_chunks(chunks)
        assert len(out) == 1
        assert out[0]["document_id"] == "doc-1"
        assert out[0]["chunk_index"] == 0
        assert out[0]["score"] == 0.9
        # Text preview is truncated to 250 chars by default
        assert len(out[0]["text_preview"]) <= 250

    def test_limit_respected(self):
        chunks = [_mk(chunk_idx=i, score=1.0 - i * 0.01) for i in range(50)]
        out = _serialize_chunks(chunks, limit=10)
        assert len(out) == 10

    def test_text_chars_param(self):
        chunks = [_mk(text="x" * 1000, chunk_idx=0)]
        out = _serialize_chunks(chunks, text_chars=50)
        assert len(out[0]["text_preview"]) == 50

    def test_doc_name_truncated(self):
        chunks = [_mk(chunk_idx=0)]
        chunks[0].doc_name = "x" * 500
        out = _serialize_chunks(chunks)
        # doc_name is truncated to 120 chars
        assert len(out[0]["doc_name"]) <= 120
