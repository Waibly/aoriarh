"""Cloisonnement du filtre Qdrant — garde-fou n°1 de la démo publique.

La démo publique tourne sur une organisation technique SANS CCN installée et
passe `org_idcc_list=None`. Ces tests verrouillent l'invariant de sécurité : le
filtre construit alors ne doit remonter QUE le corpus commun non-CCN, jamais les
documents d'une autre organisation ni une convention collective d'un secteur
tiers. Un régression ici = fuite de données → à ne jamais casser.
"""
from __future__ import annotations

from qdrant_client.models import FieldCondition, Filter

from app.rag.search import HybridSearch

_CCN = "convention_collective_nationale"
_ACCORD = "accord_branche"
_DEMO_ORG = "11111111-1111-1111-1111-111111111111"
_OTHER_ORG = "99999999-9999-9999-9999-999999999999"


def _builder() -> HybridSearch:
    # _build_org_filter est une méthode pure : on court-circuite __init__
    # (qui instancie le client Qdrant) via __new__.
    return HybridSearch.__new__(HybridSearch)


def _field_conditions(f: Filter) -> list[FieldCondition]:
    """Aplati récursivement toutes les FieldCondition d'un filtre (should/must/must_not)."""
    out: list[FieldCondition] = []
    for bucket in (f.should, f.must, f.must_not):
        for cond in bucket or []:
            if isinstance(cond, Filter):
                out.extend(_field_conditions(cond))
            elif isinstance(cond, FieldCondition):
                out.append(cond)
    return out


def _allowed_org_values(f: Filter) -> set[str]:
    """Toutes les valeurs d'organisation_id que le filtre autorise (MatchValue)."""
    values: set[str] = set()
    for cond in _field_conditions(f):
        if cond.key == "organisation_id" and getattr(cond.match, "value", None) is not None:
            values.add(cond.match.value)
    return values


class TestCloisonnementDemo:
    def test_demo_sans_ccn_ne_voit_que_org_demo_et_commun(self):
        """Org démo (org_idcc_list=None) : seules les valeurs d'org autorisées
        sont l'org démo elle-même et le corpus « common ». Aucune autre org."""
        f = _builder()._build_org_filter(_DEMO_ORG, org_idcc_list=None)
        allowed = _allowed_org_values(f)
        assert allowed == {_DEMO_ORG, "common"}
        assert _OTHER_ORG not in allowed

    def test_demo_sans_ccn_exclut_toutes_les_ccn(self):
        """Sans IDCC installé, aucun document CCN/accord de branche ne doit être
        autorisé : pas de condition `idcc`, et les types CCN sont en must_not."""
        f = _builder()._build_org_filter(_DEMO_ORG, org_idcc_list=None)

        # Aucune condition n'autorise un idcc précis (donc aucune CCN admise).
        assert not any(c.key == "idcc" for c in _field_conditions(f))

        # Les types CCN apparaissent bien dans un must_not (exclusion explicite).
        excluded_types: set[str] = set()
        for cond in f.should or []:
            if isinstance(cond, Filter):
                for mc in cond.must_not or []:
                    if isinstance(mc, FieldCondition) and mc.key == "source_type":
                        excluded_types.update(getattr(mc.match, "any", []) or [])
        assert _CCN in excluded_types
        assert _ACCORD in excluded_types

    def test_org_avec_ccn_autorise_uniquement_ses_idcc(self):
        """Une org avec CCN installée n'autorise les docs CCN que pour SES idcc,
        et jamais ceux d'une autre org (contrôle du chemin nominal)."""
        f = _builder()._build_org_filter(_DEMO_ORG, org_idcc_list=["1234"])
        idcc_values: set[str] = set()
        for cond in _field_conditions(f):
            if cond.key == "idcc":
                idcc_values.update(getattr(cond.match, "any", []) or [])
        assert idcc_values == {"1234"}
        # Toujours pas d'autre organisation accessible.
        assert _OTHER_ORG not in _allowed_org_values(f)
