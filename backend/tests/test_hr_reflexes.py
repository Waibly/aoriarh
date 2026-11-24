"""HR reflexes: articles a practitioner checks whenever a situation appears.

Cas réels (revue du 24/11/2026, démo publique) : prolongation d'arrêt jamais
reçue sans présomption de démission ; arrêt de 7 ans sans congés payés acquis.
"""

import asyncio
from types import SimpleNamespace

from app.rag.hr_reflexes import extend_reflex_context, matching_reflexes
from app.rag.search import SearchResult

PROLONGATION = (
    "la salariée nous a pas fournit sa prolongation d arrêt de travail et dis qu on ne "
    "peut pas la contacter tant quelle est en arêt de travail mais si on la pas que faire"
)
SEPT_ANS = "salarié en arrêt depuis plus de 7 ans que faire"


def _names(*texts):
    return [r.name for r in matching_reflexes(*texts)]


def test_real_questions_trigger_their_reflex():
    assert _names(PROLONGATION) == ["absence_non_justifiee"]
    assert _names(SEPT_ANS) == ["conges_pendant_arret_long"]
    assert "absence_non_justifiee" in _names("Salarié absent sans nouvelles depuis lundi")
    assert "conges_pendant_arret_long" in _names("Salariée en longue maladie, que faire ?")


def test_unrelated_questions_trigger_nothing():
    assert _names("Peut-on renouveler la période d'essai d'un cadre ?") == []
    assert _names("Le salarié n'a pas fourni son RIB") == []
    assert _names("Combien de jours de congés pour un mariage ?") == []


def _p(idx, articles, doc="doc-ct"):
    return {
        "document_id": doc,
        "chunk_index": idx,
        "source_type": "code_travail",
        "organisation_id": "common",
        "section_path": "Section",
        "article_nums": articles,
        "text": f"### Article {articles[0]}\n\nTexte.",
        "doc_name": "Code du travail — Partie législative",
    }


POINTS = [
    _p(314, ["L1237-1", "L1237-1-1"]),
    _p(189, ["R1237-13"], doc="doc-reg"),
    _p(1489, ["L3141-5"]),
]


class FakeQdrant:
    def __init__(self, points=POINTS):
        self.points = points
        self.calls = []

    def scroll(self, collection, scroll_filter=None, limit=10, **_):
        wanted = next(c.match.any for c in scroll_filter.must if c.key == "article_nums")
        self.calls.append(wanted)
        hits = [p for p in self.points if set(p["article_nums"]) & set(wanted)]
        return [SimpleNamespace(payload=p) for p in hits], None


class FailingQdrant:
    def scroll(self, *a, **k):
        raise RuntimeError("qdrant down")


def _selected(articles=("L1226-1",), idx=1):
    return SearchResult(
        text="### Article L1226-1\n\nMaintien de salaire.",
        doc_name="Code du travail — Partie législative",
        document_id="doc-ct",
        source_type="code_travail",
        norme_niveau=2,
        norme_poids=0.5,
        chunk_index=idx,
        score=0.8,
        article_nums=list(articles),
        context_chunk_indices=[idx],
    )


def _run(baseline, qdrant, texts, diagnostics=None):
    return asyncio.run(
        extend_reflex_context(baseline, qdrant, texts=texts, diagnostics=diagnostics)
    )


def test_prolongation_brings_presumed_resignation():
    baseline = [_selected()]
    diagnostics = []
    out = _run(baseline, FakeQdrant(), [PROLONGATION], diagnostics)
    assert out[0] is baseline[0]
    assert [r.article_nums for r in out[1:]] == [["L1237-1", "L1237-1-1"], ["R1237-13"]]
    assert diagnostics[0]["reflexes"] == ["absence_non_justifiee"]


def test_no_reflex_means_no_lookup():
    qdrant = FakeQdrant()
    out = _run([_selected()], qdrant, ["Période d'essai d'un cadre"])
    assert len(out) == 1 and qdrant.calls == []


def test_present_articles_not_refetched():
    qdrant = FakeQdrant()
    baseline = [_selected(("L1237-1", "L1237-1-1"), idx=314)]
    out = _run(baseline, qdrant, [PROLONGATION])
    assert qdrant.calls == [["R1237-13"]]
    assert [r.article_nums for r in out[1:]] == [["R1237-13"]]


def test_lookup_failure_never_loses_the_answer():
    baseline = [_selected()]
    diagnostics = []
    out = _run(baseline, FailingQdrant(), [SEPT_ANS], diagnostics)
    assert out == baseline
    assert diagnostics[0]["reason"] == "reflex_lookup_failed"
