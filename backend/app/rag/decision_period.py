"""Decision-date constraints, independent of relevance or presentation order."""

import json
from datetime import date, timedelta
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator
from qdrant_client.models import DatetimeRange, FieldCondition, Filter, MatchAny

DecisionSource = Literal[
    "arret_cour_cassation",
    "arret_cour_appel",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
]
DECISION_SOURCE_TYPES = get_args(DecisionSource)


class DecisionPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date_from: date | None
    date_to: date | None
    period_basis: Literal["explicit", "history"]
    source_types: list[DecisionSource] = Field(max_length=4)

    @model_validator(mode="after")
    def executable_period(self):
        if self.date_from is None and self.date_to is None:
            raise ValueError("decision_period_missing_bounds")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("decision_period_inverted")
        return self


def decision_period_filter(period: dict) -> Filter:
    """Keep other legal sources; filter decisions before vector candidate limits."""
    spec = DecisionPeriod.model_validate_json(json.dumps(period))
    # Include the whole final calendar day, including timestamped payloads.
    end = spec.date_to
    date_range = DatetimeRange(
        gte=spec.date_from,
        lt=end + timedelta(days=1) if end and end < date.max else None,
    )
    decisions = FieldCondition(
        key="source_type", match=MatchAny(any=list(DECISION_SOURCE_TYPES))
    )
    return Filter(should=[
        Filter(must_not=[decisions]),
        Filter(must=[
            FieldCondition(
                key="source_type",
                match=MatchAny(any=spec.source_types or list(DECISION_SOURCE_TYPES)),
            ),
            FieldCondition(key="date_decision", range=date_range),
        ]),
    ])


DECISION_PERIOD_PROMPT = """
PÉRIODE DES DÉCISIONS ET RECHERCHE PAR PERTINENCE
Pour résoudre une question juridique en s'appuyant sur les décisions d'une période,
renseigne decision_period et laisse chronology=null. Une année demandée n'est pas
une demande de liste des décisions les plus récentes : cherche les décisions pertinentes
dans TOUTE la période, y compris ses premiers mois. Conserve l'answer_intent du besoin
(yes_no, calculation, case_analysis, etc.).
Par exemple, « Quelle règle retenir au vu de la jurisprudence de 2025 ? » donne
decision_period={"date_from":"2025-01-01","date_to":"2025-12-31",
"period_basis":"explicit","source_types":[]} et chronology=null.
decision_period contient date_from/date_to (dates ISO ou null, au moins une borne),
period_basis (explicit ou history) et source_types (types de décisions demandés,
[] pour toutes les juridictions couvertes). Types : arret_cour_cassation,
arret_cour_appel, arret_conseil_etat, decision_conseil_constitutionnel.
Cette période concerne la DATE DES DÉCISIONS, pas la date des faits ni la date
d'application d'une règle. Les textes de loi et conventions utiles restent consultables
quelle que soit leur ancienneté. Ne déduis pas une période de décisions de la seule
mention d'une situation passée. Sans période de décisions demandée, decision_period=null.
Pour une liste, une veille ou les dernières décisions, utilise chronology avec son ordre
et ses bornes, et decision_period=null. Ne renseigne pas les deux opérations ensemble.
"""
