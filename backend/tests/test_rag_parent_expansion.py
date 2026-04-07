"""Tests for small-to-big retrieval and identifier detection."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.rag.parent_expansion import (
    MAX_PARENT_GROUPS,
    detect_identifiers,
    expand_to_parents,
    fetch_by_identifiers,
)
from app.rag.search import SearchResult


# --- detect_identifiers -------------------------------------------------------


class TestDetectIdentifiers:
    def test_detects_pourvoi_with_dot(self):
        ids = detect_identifiers("Que dit Cass. soc. n° 22-18.875")
        assert ids["numero_pourvoi"] == ["22-18.875"]
        assert ids["article_nums"] == []

    def test_detects_pourvoi_with_W_prefix(self):
        ids = detect_identifiers("Pourvoi n° W 22-18.875 contre l'arrêt")
        assert "22-18.875" in ids["numero_pourvoi"]

    def test_detects_pourvoi_without_dot(self):
        ids = detect_identifiers("pourvoi 22-18875")
        assert ids["numero_pourvoi"] == ["22-18.875"]

    def test_detects_article_l_with_dot(self):
        ids = detect_identifiers("Que dit l'article L. 4121-1 du code du travail")
        assert "L4121-1" in ids["article_nums"]

    def test_detects_article_l_without_dot(self):
        ids = detect_identifiers("article L4121-1")
        assert "L4121-1" in ids["article_nums"]

    def test_detects_article_r(self):
        ids = detect_identifiers("art. R.1234-2")
        assert "R1234-2" in ids["article_nums"]

    def test_dedupes_repeated_identifiers(self):
        ids = detect_identifiers("L4121-1 et encore L4121-1")
        assert ids["article_nums"] == ["L4121-1"]

    def test_no_match(self):
        ids = detect_identifiers("Quels sont les délais de préavis ?")
        assert ids == {"numero_pourvoi": [], "article_nums": []}

    def test_does_not_match_phone_numbers(self):
        # 06-12-34.567 → not 2-2-3 digits, should not match pourvoi pattern
        ids = detect_identifiers("appelle-moi au 06 12 34 56 78")
        assert ids["numero_pourvoi"] == []


# --- expand_to_parents --------------------------------------------------------


def _make_chunk(
    *,
    doc_id: str,
    chunk_index: int,
    text: str,
    source_type: str = "code_travail",
    article_nums: list[str] | None = None,
    score: float = 0.5,
    doc_name: str = "doc",
) -> SearchResult:
    return SearchResult(
        text=text,
        doc_name=doc_name,
        document_id=doc_id,
        source_type=source_type,
        norme_niveau=1,
        norme_poids=1.0,
        chunk_index=chunk_index,
        score=score,
        article_nums=article_nums,
    )


def _make_qdrant_mock(siblings_by_filter):
    """Build a Qdrant mock returning siblings keyed by filter signature."""
    mock = MagicMock()

    def _scroll(collection_name, scroll_filter, limit, with_payload, with_vectors):
        # Build a key from the filter conditions for matching
        conds = []
        for c in scroll_filter.must or []:
            key = c.key
            if hasattr(c.match, "value"):
                conds.append((key, c.match.value))
            elif hasattr(c.match, "any"):
                conds.append((key, tuple(c.match.any)))
        sig = tuple(sorted(conds))
        points = siblings_by_filter.get(sig, [])
        # Wrap as Qdrant point objects
        wrapped = [MagicMock(payload=p) for p in points]
        return wrapped, None

    mock.scroll = MagicMock(side_effect=_scroll)
    return mock


class TestExpandToParents:
    def test_empty_input(self):
        assert expand_to_parents([], MagicMock()) == []

    def test_jurisprudence_fetches_full_doc(self):
        # Seed: a single chunk of an arrêt; expansion should fetch all 5 chunks
        seed = _make_chunk(
            doc_id="doc-1",
            chunk_index=0,
            text="En-tête",
            source_type="arret_cour_cassation",
            score=0.8,
        )
        sibling_payloads = [
            {
                "text": f"chunk {i}",
                "doc_name": "doc",
                "document_id": "doc-1",
                "source_type": "arret_cour_cassation",
                "norme_niveau": 1,
                "norme_poids": 1.0,
                "chunk_index": i,
            }
            for i in range(5)
        ]
        qdrant = _make_qdrant_mock({
            (("document_id", "doc-1"),): sibling_payloads,
        })
        out = expand_to_parents([seed], qdrant)
        assert len(out) == 1
        merged = out[0]
        assert merged.score == 0.8
        # Merged text should contain all 5 chunks in order
        for i in range(5):
            assert f"chunk {i}" in merged.text

    def test_article_groups_by_article_num(self):
        # Two seed chunks of the same article in same doc → one merged group
        s1 = _make_chunk(
            doc_id="doc-2",
            chunk_index=3,
            text="part A",
            source_type="code_travail",
            article_nums=["L4121-1"],
            score=0.6,
        )
        s2 = _make_chunk(
            doc_id="doc-2",
            chunk_index=4,
            text="part B",
            source_type="code_travail",
            article_nums=["L4121-1"],
            score=0.5,
        )
        sibling_payloads = [
            {
                "text": f"art chunk {i}",
                "doc_name": "code",
                "document_id": "doc-2",
                "source_type": "code_travail",
                "norme_niveau": 1,
                "norme_poids": 1.0,
                "chunk_index": i,
                "article_nums": ["L4121-1"],
            }
            for i in (3, 4, 5)
        ]
        qdrant = _make_qdrant_mock({
            (("article_nums", ("L4121-1",)), ("document_id", "doc-2")): sibling_payloads,
        })
        out = expand_to_parents([s1, s2], qdrant)
        assert len(out) == 1
        merged = out[0]
        # Best score of the seeds
        assert merged.score == 0.6
        assert "art chunk 3" in merged.text
        assert "art chunk 5" in merged.text

    def test_caps_to_max_parent_groups(self):
        # Build MAX_PARENT_GROUPS + 5 distinct doc seeds
        seeds = [
            _make_chunk(
                doc_id=f"doc-{i}",
                chunk_index=0,
                text=f"t{i}",
                source_type="arret_cour_cassation",
                score=1.0 - i * 0.01,
            )
            for i in range(MAX_PARENT_GROUPS + 5)
        ]
        # Mock returns no siblings for any filter
        qdrant = _make_qdrant_mock({})
        out = expand_to_parents(seeds, qdrant)
        assert len(out) == MAX_PARENT_GROUPS

    def test_preserves_score_order(self):
        seeds = [
            _make_chunk(
                doc_id=f"doc-{i}",
                chunk_index=0,
                text="x",
                source_type="arret_cour_cassation",
                score=score,
            )
            for i, score in enumerate([0.3, 0.9, 0.5])
        ]
        qdrant = _make_qdrant_mock({})
        out = expand_to_parents(seeds, qdrant)
        scores = [r.score for r in out]
        assert scores == sorted(scores, reverse=True)


# --- fetch_by_identifiers -----------------------------------------------------


class TestFetchByIdentifiers:
    def test_no_identifiers_returns_empty(self):
        out = fetch_by_identifiers(
            MagicMock(), {"numero_pourvoi": [], "article_nums": []}, "org-1"
        )
        assert out == []

    def test_pourvoi_scrolls_qdrant(self):
        payload = {
            "text": "arrêt content",
            "doc_name": "Cass. soc.",
            "document_id": "doc-1",
            "source_type": "arret_cour_cassation",
            "chunk_index": 0,
            "norme_niveau": 1,
            "norme_poids": 1.0,
        }
        qdrant = MagicMock()
        qdrant.scroll = MagicMock(return_value=([MagicMock(payload=payload)], None))
        out = fetch_by_identifiers(
            qdrant,
            {"numero_pourvoi": ["22-18.875"], "article_nums": []},
            organisation_id="org-1",
        )
        assert len(out) == 1
        assert out[0].text == "arrêt content"
        assert qdrant.scroll.called
