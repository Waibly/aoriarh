"""Tests for small-to-big retrieval and identifier detection."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.rag.parent_expansion import (
    MAX_CHARS_PER_GROUP,
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


# --- jurisprudence-aware merging ----------------------------------------------


_META = "Cass. soc., 06/05/2026, n° 24-13.599"


def _juris_payload(doc_id: str, idx: int, label: str, body: str) -> dict:
    return {
        "text": f"{_META}\n{label}\n\n{body}",
        "doc_name": "Cass. soc. 24-13.599",
        "document_id": doc_id,
        "source_type": "arret_cour_cassation",
        "norme_niveau": 4,
        "norme_poids": 0.7,
        "chunk_index": idx,
    }


class TestJurisprudenceMerge:
    def test_keeps_holding_over_boilerplate(self):
        # A long arrêt: en-tête + faits (x2) + motifs + dispositif, > 9000 chars.
        # The holding (motifs/dispositif) sits at the END, the budget is finite,
        # so the merge must drop the boilerplate, not the ruling.
        entete = "EN-TETE blabla. " * 300 + " ENTETE_END"
        faits1 = "Faits partie un. " * 220 + " FAITS1_MARK"
        faits2 = "Faits partie deux. " * 220 + " FAITS2_MARK"
        motifs = "Réponse de la Cour. " + "motif blah. " * 130 + " MOTIFS_HOLDING"
        dispo = "PAR CES MOTIFS REJETTE. " + "dispositif blah. " * 30 + " DISPOSITIF_END"

        doc_id = "arret-1"
        payloads = [
            _juris_payload(doc_id, 0, "[En-tête]", entete),
            _juris_payload(doc_id, 1, "[Faits et procédure]", faits1),
            _juris_payload(doc_id, 2, "[Faits et procédure]", faits2),
            _juris_payload(doc_id, 3, "[Motifs de la décision]", motifs),
            _juris_payload(doc_id, 4, "[Dispositif]", dispo),
        ]
        # Seed = the chunk the reranker matched (the motifs).
        seed = _make_chunk(
            doc_id=doc_id,
            chunk_index=3,
            text=payloads[3]["text"],
            source_type="arret_cour_cassation",
            score=0.85,
        )
        qdrant = _make_qdrant_mock({(("document_id", doc_id),): payloads})

        out = expand_to_parents([seed], qdrant)
        assert len(out) == 1
        merged = out[0].text

        # The ruling survives even though it is at the end of the document.
        assert "Réponse de la Cour" in merged
        assert "MOTIFS_HOLDING" in merged
        assert "DISPOSITIF_END" in merged
        assert "[Motifs de la décision]" in merged
        assert "[Dispositif]" in merged
        # The boilerplate header is dropped (lowest priority, largest).
        assert "ENTETE_END" not in merged
        # A gap marker appears where chunks were dropped.
        assert "[…]" in merged
        # The per-chunk meta header is kept exactly once, not repeated per chunk.
        assert merged.count(_META) == 1
        # Budget respected.
        assert len(merged) <= MAX_CHARS_PER_GROUP

    def test_sets_seed_text_to_matched_passage(self):
        motifs = "Réponse de la Cour. " + "motif blah. " * 50 + " MOTIFS_HOLDING"
        doc_id = "arret-2"
        payloads = [
            _juris_payload(doc_id, 0, "[En-tête]", "EN-TETE court."),
            _juris_payload(doc_id, 1, "[Motifs de la décision]", motifs),
        ]
        seed = _make_chunk(
            doc_id=doc_id,
            chunk_index=1,
            text=payloads[1]["text"],
            source_type="arret_cour_cassation",
            score=0.9,
        )
        qdrant = _make_qdrant_mock({(("document_id", doc_id),): payloads})

        out = expand_to_parents([seed], qdrant)
        seed_text = out[0].seed_text
        # Excerpt source = the matched passage, stripped of header and label.
        assert seed_text is not None
        assert "MOTIFS_HOLDING" in seed_text
        assert _META not in seed_text
        assert "[Motifs de la décision]" not in seed_text

    def test_dedupes_overlap_and_repeated_header(self):
        # Two consecutive chunks of the same section share an overlap region
        # (as force-split chunks do). The merge must stitch it, not repeat it.
        overlap = "ZONE_DE_CHEVAUCHEMENT_UNIQUE_0123456789 "  # > 20 chars
        body1 = "Debut des faits. " * 5 + overlap
        body2 = overlap + "Suite des faits. " * 5
        doc_id = "arret-3"
        payloads = [
            _juris_payload(doc_id, 0, "[Faits et procédure]", body1),
            _juris_payload(doc_id, 1, "[Faits et procédure]", body2),
        ]
        seed = _make_chunk(
            doc_id=doc_id,
            chunk_index=0,
            text=payloads[0]["text"],
            source_type="arret_cour_cassation",
            score=0.7,
        )
        qdrant = _make_qdrant_mock({(("document_id", doc_id),): payloads})

        merged = expand_to_parents([seed], qdrant)[0].text
        assert merged.count("ZONE_DE_CHEVAUCHEMENT_UNIQUE_0123456789") == 1
        assert merged.count(_META) == 1
        assert merged.count("[Faits et procédure]") == 1


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


# --- legislation floor preservation ------------------------------------------


def _jur(i: int, score: float) -> SearchResult:
    return _make_chunk(
        doc_id=f"jur{i}", chunk_index=0, text=f"arret {i}",
        source_type="arret_cour_cassation", score=score, doc_name=f"Cass {i}",
    )


def _code(i: int, art: str, score: float) -> SearchResult:
    return _make_chunk(
        doc_id=f"code{i}", chunk_index=0, text=f"article {art}",
        source_type="code_travail", article_nums=[art], score=score,
        doc_name="Code du travail",
    )


def _n_legislation(results: list[SearchResult]) -> int:
    return sum(1 for r in results if r.source_type.startswith("code_"))


class TestLegislationFloorPreservation:
    def _results(self) -> list[SearchResult]:
        # 10 jurisprudence (highest scores) + 2 code articles ranked 11–12
        return [_jur(i, 0.90 - i * 0.02) for i in range(10)] + [
            _code(1, "L2411-1", 0.62),
            _code(2, "R2421-3", 0.60),
        ]

    def test_default_drops_low_ranked_legislation(self):
        out = expand_to_parents(self._results(), _make_qdrant_mock({}))
        assert len(out) == MAX_PARENT_GROUPS
        assert _n_legislation(out) == 0  # code cut by the cap, as before

    def test_min_legislation_preserves_articles(self):
        out = expand_to_parents(
            self._results(), _make_qdrant_mock({}), min_legislation=2,
        )
        assert len(out) == MAX_PARENT_GROUPS
        assert _n_legislation(out) == 2
        arts = sorted(r.article_nums[0] for r in out if r.article_nums)
        assert arts == ["L2411-1", "R2421-3"]

    def test_pure_jurisprudence_not_polluted(self):
        # No legislation in the reranked input → nothing is forced in.
        pure = [_jur(i, 0.90 - i * 0.02) for i in range(12)]
        out = expand_to_parents(pure, _make_qdrant_mock({}), min_legislation=2)
        assert _n_legislation(out) == 0

    def test_legislation_already_kept_is_not_duplicated(self):
        # One code article already in the top-10 → no spurious swapping.
        mixed = [_code(1, "L1111-1", 0.95)] + [
            _jur(i, 0.90 - i * 0.02) for i in range(11)
        ]
        out = expand_to_parents(mixed, _make_qdrant_mock({}), min_legislation=2)
        assert _n_legislation(out) == 1
