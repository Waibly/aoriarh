"""Sanctions of a selected Code obligation, found by explicit citation.

Cas réel (13/11/2026) : question DUERP. R4121-2 était retenu, mais ni l'amende
administrative (L8115-1 6°, montant en L8115-3) ni l'amende pénale (R4741-1)
n'arrivaient au modèle : ces articles parlent de sanctions en général et ne
ressemblent pas à la question.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.rag import sanction_links
from app.rag.sanction_links import cited_references, extend_sanction_context, split_references
from app.rag.search import SearchResult

LEG = "doc-leg"
REG = "doc-reg"
AMENDES = "Partie législative > Huitième partie > Chapitre V : Amendes administratives"
PENAL = "Partie réglementaire > Livre VII > Titre IV : Dispositions pénales > Chapitre Ier"
PORTAGE = "Partie législative > Titre V > Chapitre V : Dispositions pénales > Section 3 : Portage"


def _p(doc, idx, source_type, section, articles, text):
    return {
        "document_id": doc,
        "chunk_index": idx,
        "source_type": source_type,
        "organisation_id": "common",
        "section_path": section,
        "article_nums": articles,
        "text": text,
        "doc_name": doc,
    }


POINTS = [
    _p(LEG, 10, "code_travail", "Partie législative > Livre Ier > Chapitre Ier : Obligations",
       ["L4121-3-1"], "Le document unique d'évaluation des risques…"),
    _p(LEG, 50, "code_travail", AMENDES, ["L8115-1"],
       "L'autorité administrative peut prononcer une amende en cas de manquement :\n"
       "1° Aux durées maximales fixées aux articles L. 3121-18 à L. 3121-25 ;"),
    _p(LEG, 51, "code_travail", AMENDES, ["L8115-1"],
       "6° Aux dispositions des I et II de l'article L. 4121-3-1 relatives au document "
       "unique, en cas d'absence du document."),
    _p(LEG, 52, "code_travail", AMENDES, ["L8115-2", "L8115-3"],
       "Le montant maximal de l'amende est de 4 000 euros par travailleur concerné."),
    _p(LEG, 53, "code_travail", "Partie législative > Chapitre VI : Autre", ["L8116-1"],
       "Sans rapport."),
    _p(LEG, 70, "code_travail", PORTAGE, ["L1255-14"],
       "14° Les obligations définies aux articles L. 4121-1 à L. 4121-5."),
    _p(REG, 5, "code_travail_reglementaire", PENAL, ["R4741-1"],
       "Le fait de ne pas transcrire ou de ne pas mettre à jour les résultats de "
       "l'évaluation des risques, dans les conditions prévues aux articles R. 4121-1 "
       "et R. 4121-2, est puni de l'amende des contraventions de cinquième classe."),
]


class FakeQdrant:
    def __init__(self, points):
        self.points = points
        self.scrolls = 0

    def scroll(self, collection, scroll_filter=None, offset=None, limit=1000, **_):
        self.scrolls += 1
        return [SimpleNamespace(payload=p) for p in self.points], None


class FailingQdrant:
    def scroll(self, *a, **k):
        raise RuntimeError("qdrant down")


def _selected_duerp_article():
    return SearchResult(
        text="### Article R4121-2\nLa mise à jour du document unique… "
        "Le document est tenu à disposition dans les conditions de l'article L. 4121-3-1.",
        doc_name="Code du travail — Partie réglementaire",
        document_id=REG,
        source_type="code_travail_reglementaire",
        norme_niveau=2,
        norme_poids=0.5,
        chunk_index=1,
        score=0.7,
        article_nums=["R4121-2"],
        context_chunk_indices=[1],
    )


@pytest.fixture(autouse=True)
def _fresh_cache():
    sanction_links.clear_cache()
    yield
    sanction_links.clear_cache()


def _run(baseline, qdrant, diagnostics=None):
    return asyncio.run(extend_sanction_context(baseline, qdrant, diagnostics=diagnostics))


def test_ranges_are_expanded_but_marked():
    explicit, ranged = split_references("articles L. 3121-18 à L. 3121-21 et R. 4121-1")
    assert explicit == {"L3121-18", "L3121-21", "R4121-1"}
    assert ranged == {"L3121-19", "L3121-20"}
    assert "L3121-20" in cited_references("articles L. 3121-18 à L. 3121-21")


def test_duerp_brings_administrative_and_penal_fines():
    diagnostics = []
    out = _run([_selected_duerp_article()], FakeQdrant(POINTS), diagnostics)

    added = out[1:]
    articles = [a for r in added for a in r.article_nums]
    assert "R4741-1" in articles  # amende pénale (cite R4121-2, article retenu)
    assert "L8115-1" in articles  # amende administrative (cite L4121-3-1, renvoi)
    l8115 = next(r for r in added if "L8115-1" in r.article_nums)
    # Article complet + passage suivant du même chapitre (le montant).
    assert l8115.context_chunk_indices == [50, 51, 52]
    assert "4 000 euros" in l8115.text
    assert "Sans rapport" not in l8115.text
    # Une simple fourchette « L. 4121-1 à L. 4121-5 » ne suffit pas pour un renvoi.
    assert "L1255-14" not in articles
    info = next(d for d in diagnostics if d["status"] == "sanction_links")
    assert info["added_groups"] == 2


def test_baseline_kept_first_and_unchanged():
    base = _selected_duerp_article()
    out = _run([base], FakeQdrant(POINTS))
    assert out[0] is base


def test_already_present_sanction_not_duplicated():
    present = SearchResult(
        text="R4741-1 …", doc_name="x", document_id=REG,
        source_type="code_travail_reglementaire", norme_niveau=2, norme_poids=0.5,
        chunk_index=5, score=0.6, article_nums=["R4741-1"], context_chunk_indices=[5],
    )
    out = _run([_selected_duerp_article(), present], FakeQdrant(POINTS))
    assert sum("R4741-1" in (r.article_nums or []) for r in out) == 1


def test_no_code_article_selected_means_no_lookup():
    juris = SearchResult(
        text="Arrêt…", doc_name="CA", document_id="arret", source_type="arret_cour_appel",
        norme_niveau=5, norme_poids=0.5, chunk_index=0, score=0.8,
    )
    qdrant = FakeQdrant(POINTS)
    assert _run([juris], qdrant) == [juris]
    assert qdrant.scrolls == 0


def test_index_is_cached():
    qdrant = FakeQdrant(POINTS)
    _run([_selected_duerp_article()], qdrant)
    _run([_selected_duerp_article()], qdrant)
    assert qdrant.scrolls == 1


def test_lookup_failure_never_loses_the_answer():
    base = [_selected_duerp_article()]
    diagnostics = []
    assert _run(base, FailingQdrant(), diagnostics) == base
    assert diagnostics[0]["reason"] == "sanction_lookup_failed"
