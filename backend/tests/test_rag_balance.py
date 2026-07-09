"""Tests de la balance 'hiérarchie des normes' (_balance_source_types) :
la règle applicable (loi/code/décret) ne doit pas être noyée sous la
jurisprudence ou la CCN en tête de la liste finale."""
from app.rag.agent import (
    RAGAgent,
    _CCN_SOURCE_TYPES,
    _JURIS_SOURCE_TYPES,
    _LEGISLATION_SOURCE_TYPES,
    _BALANCE_JURIS_CAP,
    _BALANCE_CCN_CAP,
)
from app.rag.search import SearchResult

# Garde-fou : les catégories doivent être peuplées (sinon la balance est inerte).
RULE_ST = "code_travail"
JURIS_ST = "arret_cour_appel"
CCN_ST = "convention_collective_nationale"


def _r(source_type: str, score: float, cid: str = "d", chunk: int = 0) -> SearchResult:
    return SearchResult(
        text="x", doc_name=source_type, document_id=cid, source_type=source_type,
        norme_niveau=5, norme_poids=0.8, chunk_index=chunk, score=score,
    )


def test_categories_are_populated():
    assert RULE_ST in _LEGISLATION_SOURCE_TYPES
    assert JURIS_ST in _JURIS_SOURCE_TYPES
    assert CCN_ST in _CCN_SOURCE_TYPES


def test_promotes_competitive_rule_to_top():
    # top = arrêt 0.50 ; meilleure règle 0.40 -> 0.40/0.50 = 0.80 >= 0.7 -> promue
    results = [_r(JURIS_ST, 0.50, "a1"), _r(JURIS_ST, 0.48, "a2"),
               _r(RULE_ST, 0.40, "c1"), _r(JURIS_ST, 0.46, "a3")]
    out = RAGAgent._balance_source_types(results)
    assert out[0].source_type == RULE_ST
    assert len(out) == 4  # rien supprimé


def test_does_not_promote_weak_rule():
    # règle 0.30 vs top arrêt 0.90 -> 0.33 < 0.7 -> question jurisprudentielle, pas de promotion
    results = [_r(JURIS_ST, 0.90, "a1"), _r(RULE_ST, 0.30, "c1"), _r(JURIS_ST, 0.50, "a2")]
    out = RAGAgent._balance_source_types(results)
    assert out[0].source_type == JURIS_ST
    assert out[0].score == 0.90


def test_caps_jurisprudence_defers_excess():
    # 6 arrêts + 1 règle faible (pas de promotion) ; cap arrêts = 4
    results = [_r(JURIS_ST, 0.9 - i * 0.1, f"a{i}") for i in range(6)]
    results.append(_r(RULE_ST, 0.35, "c1"))
    out = RAGAgent._balance_source_types(results)
    assert len(out) == 7  # rien supprimé
    # la règle passe devant les arrêts excédentaires (reportés en fin)
    juris_before_rule = 0
    for r in out:
        if r.source_type == RULE_ST:
            break
        juris_before_rule += 1
    assert juris_before_rule == _BALANCE_JURIS_CAP
    # les 2 derniers sont les arrêts excédentaires reportés
    assert all(r.source_type == JURIS_ST for r in out[-2:])


def test_caps_ccn_defers_excess():
    results = [_r(CCN_ST, 0.9 - i * 0.05, f"n{i}") for i in range(6)]
    results.append(_r(RULE_ST, 0.30, "c1"))  # règle faible : pas de promotion
    out = RAGAgent._balance_source_types(results)
    assert len(out) == 7
    ccn_before_rule = 0
    for r in out:
        if r.source_type == RULE_ST:
            break
        ccn_before_rule += 1
    assert ccn_before_rule == _BALANCE_CCN_CAP


def test_small_list_untouched():
    results = [_r(JURIS_ST, 0.9, "a1"), _r(CCN_ST, 0.8, "n1")]
    out = RAGAgent._balance_source_types(results)
    assert out == results


def test_nothing_dropped_and_all_preserved():
    results = [_r(JURIS_ST, 0.9, "a1"), _r(CCN_ST, 0.8, "n1"),
               _r(RULE_ST, 0.7, "c1"), _r(JURIS_ST, 0.6, "a2")]
    out = RAGAgent._balance_source_types(results)
    assert sorted(id(r) for r in out) == sorted(id(r) for r in results)
