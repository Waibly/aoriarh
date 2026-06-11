"""Tests for source-type intent detection (directed triggers only).

The false positives below are real prod questions that emptied the candidate
pool when a bare mention ("ccn", "contrat de travail") hard-restricted the
search. They must NOT trigger anymore.
"""
from __future__ import annotations

from app.rag.source_intent import detect_source_intent


def _types(query: str) -> set[str]:
    out: set[str] = set()
    for source_types, _needs_org in detect_source_intent(query):
        out.update(source_types)
    return out


class TestNoFalsePositives:
    """Bare mentions of a source are generic legal questions — no filter."""

    def test_ccn_mention_prod_case(self):
        q = ("Si l'employeur a une ccn il faut la prendre en compte "
             "dans le calcul des indemnités de licenciement")
        assert detect_source_intent(q) == []

    def test_rupture_contrat_de_travail_prod_case(self):
        q = ("Comment un employeur peut-il préparer et conduire une rupture "
             "du contrat de travail afin de limiter les risques prud'homaux "
             "à chaque étape de la procédure ?")
        assert detect_source_intent(q) == []

    def test_convention_de_forfait(self):
        q = "La convention de forfait doit-elle être écrite ?"
        assert detect_source_intent(q) == []

    def test_clause_dans_le_contrat(self):
        q = ("Une clause de non-concurrence dans le contrat de travail "
             "est-elle valable sans contrepartie ?")
        assert detect_source_intent(q) == []

    def test_code_du_travail_et_decrets_prod_case(self):
        q = "vérifie les textes du Code du travail et les décrets/arrêtés associés"
        assert detect_source_intent(q) == []

    def test_cassation_citation(self):
        q = ("La Cour de cassation a déjà jugé qu'un licenciement est sans "
             "cause réelle et sérieuse dans ce cas ?")
        assert detect_source_intent(q) == []

    def test_un_accord_entreprise_generique(self):
        q = "Un accord d'entreprise peut-il déroger à la CCN ?"
        assert detect_source_intent(q) == []


class TestDirectedTriggers:
    """Questions directed at a source category must keep triggering."""

    def test_que_dit_la_ccn(self):
        assert "convention_collective_nationale" in _types(
            "Que dit la CCN sur les congés d'ancienneté ?"
        )

    def test_que_prevoit_le_reglement_interieur(self):
        assert "reglement_interieur" in _types(
            "Que prévoit notre règlement intérieur sur les retards ?"
        )

    def test_selon_ma_convention_collective(self):
        assert "convention_collective_nationale" in _types(
            "Selon ma convention collective, quel est le préavis ?"
        )

    def test_ccn_prevoit_elle(self):
        assert "convention_collective_nationale" in _types(
            "La CCN prévoit-elle une prime d'ancienneté ?"
        )

    def test_dans_la_ccn(self):
        assert "convention_collective_nationale" in _types(
            "Vérifie dans la CCN les informations sur le report des congés"
        )

    def test_aux_termes_de_la_convention_collective(self):
        assert "convention_collective_nationale" in _types(
            "Aux termes de la convention collective nationale, l'article 3.4 "
            "prévoit une indemnité"
        )

    def test_que_dit_le_code_du_travail(self):
        assert "code_travail" in _types(
            "Que dit le code du travail sur le préavis de démission ?"
        )

    def test_mon_contrat(self):
        assert "contrat_travail" in _types(
            "Mon contrat prévoit une clause de mobilité, est-elle valable ?"
        )

    def test_nos_accords(self):
        assert "accord_entreprise" in _types(
            "Que contiennent nos accords sur le télétravail ?"
        )

    def test_jurisprudence_sur(self):
        assert "arret_cour_cassation" in _types(
            "Y a-t-il de la jurisprudence sur le licenciement pendant un arrêt maladie ?"
        )

    def test_notre_ri(self):
        assert "reglement_interieur" in _types(
            "Notre RI peut-il interdire le téléphone personnel ?"
        )
