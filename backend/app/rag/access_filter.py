"""One access policy for semantic searches and identifier/parent lookups."""

from contextvars import ContextVar

from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsEmptyCondition,
    MatchAny,
    MatchValue,
    PayloadField,
)

from app.services.territoire import parse_territoire

# Lieu d'implantation de l'organisation pour la préparation en cours. Fixé une
# fois par RAGAgent.prepare_context : les nombreuses recherches et lectures de la
# préparation (y compris celles lancées via asyncio.to_thread, qui copient le
# contexte) appliquent ainsi la même règle sans relayer le territoire partout.
# None = territoire inconnu → aucun accord régional n'est écarté.
current_territoire: ContextVar[str | None] = ContextVar("current_territoire", default=None)


def set_current_territoire(value: str | None) -> None:
    """Code ou libellé de territoire (contexte d'organisation) ; None = inconnu."""
    current_territoire.set(parse_territoire(value).value if value else None)


def _territory_condition(territoire: str) -> Filter:
    """Textes sans territoire propre, ou propres au territoire de l'organisation."""
    return Filter(
        should=[
            IsEmptyCondition(is_empty=PayloadField(key="territoires")),
            FieldCondition(key="territoires", match=MatchAny(any=[territoire])),
        ]
    )


def build_org_access_filter(
    organisation_id: str | None,
    org_idcc_list: list[str] | None = None,
    authorized_private_document_ids: list[str] | None = None,
    territoire: str | None = None,
) -> Filter | None:
    # Only explicit administrative callers may omit the organisation.
    if not organisation_id:
        return None
    territoire = territoire or current_territoire.get()
    ccn_types = ["convention_collective_nationale", "accord_branche"]
    should = [
        FieldCondition(key="organisation_id", match=MatchValue(value=organisation_id)),
        Filter(
            must=[FieldCondition(key="organisation_id", match=MatchValue(value="common"))],
            must_not=[FieldCondition(key="source_type", match=MatchAny(any=ccn_types))],
        ),
    ]
    if org_idcc_list:
        for source_type in ccn_types:
            must = [
                FieldCondition(key="organisation_id", match=MatchValue(value="common")),
                FieldCondition(key="source_type", match=MatchValue(value=source_type)),
                FieldCondition(key="idcc", match=MatchAny(any=org_idcc_list)),
            ]
            should.append(Filter(must=must))
    private_exclusion = Filter(
        must_not=[FieldCondition(key="private", match=MatchValue(value=True))]
    )
    if authorized_private_document_ids:
        private_exclusion = Filter(
            should=[
                private_exclusion,
                FieldCondition(
                    key="document_id", match=MatchAny(any=authorized_private_document_ids)
                ),
            ]
        )
    must: list = [Filter(should=should), private_exclusion]
    # Accord régional d'une convention nationale (valeur du point en
    # Martinique…) : seulement pour une entreprise de ce territoire. Vaut aussi
    # pour les copies de CCN propres à une organisation ; seuls ces accords
    # portent `territoires`, tout le reste passe.
    if territoire:
        must.append(_territory_condition(territoire))
    return Filter(must=must)
