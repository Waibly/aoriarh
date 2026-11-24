"""Exceptions stated right after a selected Code article.

Cas réel (05/11/2026, Cilam) : L1243-8 (indemnité de fin de CDD) était retenu,
pas L1243-10 qui suit (« n'est pas due … rupture anticipée à l'initiative du
salarié »). La réponse annonçait les 10 % sans réserve.
"""

import asyncio
from types import SimpleNamespace

from app.rag.exception_links import extend_exception_context, opens_with_exception
from app.rag.search import SearchResult

DOC = "doc-ct"
ECHEANCE = "Titre IV > Chapitre III > Section 2 : Echéance du terme du contrat"
RENOUV = "Titre IV > Chapitre III > Section 3 : Renouvellement du contrat"


def _p(idx, section, articles, text, org="common"):
    return {
        "document_id": DOC,
        "chunk_index": idx,
        "source_type": "code_travail",
        "organisation_id": org,
        "section_path": section,
        "article_nums": articles,
        "text": text,
        "doc_name": "Code du travail — Partie législative",
    }


POINTS = {
    370: _p(
        370,
        ECHEANCE,
        ["L1243-10", "L1243-11"],
        "### Article L1243-10\n\nL'indemnité de fin de contrat n'est pas due :\n\n"
        "4° En cas de rupture anticipée du contrat due à l'initiative du salarié.\n\n"
        "### Article L1243-11\n\nLorsque la relation contractuelle se poursuit…",
    ),
    371: _p(371, RENOUV, ["L1243-13"], "### Article L1243-13\n\nPar dérogation, autre section."),
}


class FakeQdrant:
    def __init__(self, points=POINTS):
        self.points = points
        self.calls = []

    def scroll(self, collection, scroll_filter=None, limit=10, **_):
        wanted = next(c.match.any for c in scroll_filter.must if c.key == "chunk_index")
        self.calls.append(sorted(wanted))
        return [SimpleNamespace(payload=self.points[i]) for i in wanted if i in self.points], None


class FailingQdrant:
    def scroll(self, *a, **k):
        raise RuntimeError("qdrant down")


def _indemnite_group(source_type="code_travail"):
    return SearchResult(
        text="### Article L1243-8\n\nLe salarié a droit… à une indemnité de fin de contrat.\n\n"
        "### Article L1243-9\n\nUne convention peut limiter l'indemnité à 6 %.",
        doc_name="Code du travail — Partie législative",
        document_id=DOC,
        source_type=source_type,
        norme_niveau=2,
        norme_poids=0.5,
        chunk_index=369,
        score=0.8,
        article_nums=["L1243-8", "L1243-9"],
        section_path=ECHEANCE,
        context_chunk_indices=[369],
    )


def _run(baseline, qdrant, **kwargs):
    return asyncio.run(extend_exception_context(baseline, qdrant, **kwargs))


def test_opening_detection():
    assert opens_with_exception("### Article L1\n\nL'indemnité n'est pas due :")
    assert opens_with_exception("### Article L2\n\nPar dérogation aux dispositions de L. 1…")
    assert opens_with_exception("### Article L3\n\nToutefois, l'employeur peut…")
    assert not opens_with_exception("### Article L4\n\nLe contrat cesse de plein droit.")
    # Buried far in a long article: not an exception to the preceding rule.
    assert not opens_with_exception("### Article L5\n\n" + "x " * 200 + "n'est pas due")


def test_indemnite_brings_its_exceptions():
    baseline = [_indemnite_group()]
    diagnostics = []
    out = _run(baseline, FakeQdrant(), diagnostics=diagnostics)
    assert out[0] is baseline[0]
    assert [r.article_nums for r in out[1:]] == [["L1243-10", "L1243-11"]]
    assert out[1].context_chunk_indices == [370]
    info = next(d for d in diagnostics if d["status"] == "exception_links")
    assert info["added_groups"] == 1


def test_stops_at_section_change():
    # 371 opens with « Par dérogation » but belongs to the next section.
    out = _run([_indemnite_group()], FakeQdrant())
    assert all("L1243-13" not in (r.article_nums or []) for r in out)


def test_no_addition_without_exception_wording():
    points = {370: _p(370, ECHEANCE, ["L1243-10"], "### Article L1243-10\n\nLe contrat cesse.")}
    out = _run([_indemnite_group()], FakeQdrant(points))
    assert len(out) == 1


def test_already_present_passage_not_duplicated():
    present = _indemnite_group()
    exception = SearchResult(
        text=POINTS[370]["text"],
        doc_name="Code du travail — Partie législative",
        document_id=DOC,
        source_type="code_travail",
        norme_niveau=2,
        norme_poids=0.5,
        chunk_index=370,
        score=0.5,
        article_nums=["L1243-10", "L1243-11"],
        context_chunk_indices=[370],
    )
    out = _run([present, exception], FakeQdrant())
    assert len(out) == 2


def test_only_seed_groups_are_followed():
    added_reference = _indemnite_group()
    out = _run([added_reference], FakeQdrant(), seeds=[])
    assert out == [added_reference]


def test_non_code_sources_ignored():
    qdrant = FakeQdrant()
    out = _run([_indemnite_group("arret_cour_cassation")], qdrant)
    assert len(out) == 1 and qdrant.calls == []


def test_lookup_failure_never_loses_the_answer():
    baseline = [_indemnite_group()]
    diagnostics = []
    out = _run(baseline, FailingQdrant(), diagnostics=diagnostics)
    assert out == baseline
    assert diagnostics[0]["reason"] == "exception_lookup_failed"
