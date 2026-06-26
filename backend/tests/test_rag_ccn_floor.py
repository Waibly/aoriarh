"""Tests du repêchage CCN dans le plancher de pertinence et du plancher de
confiance conscient du type de source (correctif « la CCN ne remonte plus »)."""
from __future__ import annotations

import app.rag.config as rag_config
from app.rag.agent import RAGAgent, _assess_confidence
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


_CCN = "convention_collective_nationale"
_ACCORD = "accord_branche"


class TestCcnRescue:
    def test_ccn_below_floor_is_rescued(self):
        """Une question cadrée « Code du travail » : la législation passe au-
        dessus du plancher, la CCN de l'org tombe juste en dessous → on la
        repêche pour qu'elle atteigne quand même la génération."""
        results = [
            _mk(0.70, "loi1"), _mk(0.60, "loi2"), _mk(0.50, "loi3"),
            _mk(0.45, "loi4"),
            _mk(0.34, "ccn1", _CCN),  # sous le plancher (0.35) mais ≥ 0.15
        ]
        kept, dropped = RAGAgent._apply_score_floor(results)
        assert "ccn1" in {r.document_id for r in kept}
        assert "ccn1" not in {r.document_id for r in dropped}

    def test_rescue_capped(self):
        """Au plus CCN_FLOOR_RESCUE groupes CCN repêchés."""
        results = [_mk(0.70, f"loi{i}") for i in range(4)]
        results += [_mk(0.30 - i * 0.01, f"ccn{i}", _CCN) for i in range(5)]
        kept, _ = RAGAgent._apply_score_floor(results)
        rescued = [r for r in kept if r.source_type == _CCN]
        assert len(rescued) == rag_config.CCN_FLOOR_RESCUE
        # Ce sont les MEILLEURS groupes CCN qui sont repêchés.
        assert [r.document_id for r in rescued] == ["ccn0", "ccn1"]

    def test_ccn_too_low_not_rescued(self):
        """Une CCN sous le plancher dédié (0.15) reste hors-sujet : pas repêchée."""
        results = [_mk(0.70, f"loi{i}") for i in range(4)]
        results.append(_mk(0.05, "ccn_noise", _CCN))
        kept, dropped = RAGAgent._apply_score_floor(results)
        assert "ccn_noise" in {r.document_id for r in dropped}

    def test_accord_branche_also_rescued(self):
        results = [_mk(0.70, f"loi{i}") for i in range(4)]
        results.append(_mk(0.25, "accord1", _ACCORD))
        kept, _ = RAGAgent._apply_score_floor(results)
        assert "accord1" in {r.document_id for r in kept}


class TestEnsureCcnRepresented:
    def test_reinjects_ccn_cut_at_rerank(self):
        """La CCN présente dans le pool mais coupée au rerank est réinjectée."""
        pool = [_mk(0.9, f"loi{i}") for i in range(15)]
        pool += [_mk(0.4, "ccn1", _CCN), _mk(0.35, "ccn2", _CCN), _mk(0.2, "ccn3", _CCN)]
        reranked = pool[:15]  # que de la législation
        out = RAGAgent._ensure_ccn_represented(pool, reranked, ["0413"])
        ccn = [r.document_id for r in out if r.source_type == _CCN]
        assert ccn == ["ccn1", "ccn2"]  # top CCN_FLOOR_RESCUE, par score

    def test_noop_when_ccn_already_present(self):
        reranked = [_mk(0.9, "loi"), _mk(0.5, "ccn1", _CCN)]
        out = RAGAgent._ensure_ccn_represented(reranked, reranked, ["0413"])
        assert out is reranked

    def test_noop_when_org_has_no_ccn(self):
        pool = [_mk(0.9, "loi"), _mk(0.3, "ccn1", _CCN)]
        reranked = [_mk(0.9, "loi")]
        out = RAGAgent._ensure_ccn_represented(pool, reranked, None)
        assert out is reranked

    def test_noop_when_pool_has_no_ccn(self):
        pool = [_mk(0.9, f"loi{i}") for i in range(15)]
        reranked = pool[:15]
        out = RAGAgent._ensure_ccn_represented(pool, reranked, ["0413"])
        assert all(r.source_type != _CCN for r in out)


class TestAssessConfidence:
    def test_strong_general_source_is_confident(self):
        results = [_mk(0.7, "loi"), _mk(0.34, "ccn", _CCN)]
        best, low = _assess_confidence(results)
        assert best == 0.7
        assert low is False

    def test_ccn_only_moderate_is_confident(self):
        """Question portant sur la convention : pool restreint aux CCN, scores
        modérés — on ne doit PAS basculer en faible confiance."""
        results = [_mk(0.34, "ccn1", _CCN), _mk(0.32, "ccn2", _CCN)]
        _, low = _assess_confidence(results)
        assert low is False

    def test_everything_weak_is_low_confidence(self):
        results = [_mk(0.20, "ccn", _CCN), _mk(0.18, "loi")]
        _, low = _assess_confidence(results)
        assert low is True

    def test_empty(self):
        best, low = _assess_confidence([])
        assert best is None and low is False
