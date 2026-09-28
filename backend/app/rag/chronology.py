"""Typed catalogue operations, independent of generated answer quality."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChronologySource = Literal[
    "loi",
    "ordonnance",
    "decret",
    "arrete",
    "boss",
    "arret_cour_cassation",
    "arret_cour_appel",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
]


class ChronologyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date_kind: Literal["publication", "decision", "effective", "update", "event"]
    date_from: date | None
    date_to: date | None
    period_basis: Literal["explicit", "history", "none"]
    source_types: list[ChronologySource] = Field(max_length=9)
    jurisdiction: str | None = Field(max_length=100)
    chamber: str | None = Field(max_length=100)
    topic: str | None = Field(max_length=1000)
    order: Literal["newest", "oldest"]
    limit: int = Field(ge=1, le=10)
    offset: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def executable_period(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("chronology_inverted_period")
        if self.period_basis == "none" and (self.date_from or self.date_to):
            raise ValueError("chronology_unattributed_period")
        if self.period_basis != "none" and not (self.date_from or self.date_to):
            raise ValueError("chronology_missing_period")
        return self


CHRONOLOGY_PROMPT = """
RECHERCHE CHRONOLOGIQUE
Pour les derniers textes, nouveautés, actualités, décisions récentes, évolutions depuis
une date ou entrées en vigueur, renseigne chronology et answer_intent=legal_news.
Pour une règle actuellement applicable, chronology=null : un texte récent ne suffit pas
à établir le droit en vigueur. Le catalogue est celui des sources officielles collectées
par AORIA RH ; il ne couvre pas intégralement le Journal officiel ou toutes les juridictions.
chronology contient :
- date_kind : publication (publication officielle), decision (date d'arrêt), effective
  (entrée en vigueur), update (mise à jour officielle), event (veille mêlant publications,
  décisions et mises à jour ; chaque résultat garde la nature exacte de sa date).
- date_from/date_to : dates ISO ou null. Reprends une période explicite exactement,
  en résolvant les expressions relatives avec current_date. Pour « depuis », la borne de
  fin est current_date ; pour un mois, utilise son premier et dernier jour. Pour « depuis
  notre dernier échange », utilise sa date seulement si l'historique la fournit.
- period_basis : explicit, history ou none. « Derniers », « récents », « quoi de neuf »
  sans période donnent none et deux bornes null. N'invente pas sept ou trente jours.
- source_types : types précis demandés, [] pour toutes les sources officielles couvertes.
  Types disponibles : loi, ordonnance, decret, arrete, boss, arret_cour_cassation,
  arret_cour_appel, arret_conseil_etat, decision_conseil_constitutionnel.
- jurisdiction/chamber : libellé demandé ou null (ex. chambre="sociale").
- topic : sujet juridique à rechercher ou null pour une liste chronologique générale.
  « décrets » est un type, pas un thème. Pour une veille RH large, topic="droit social".
- order : newest par défaut, oldest si demandé. limit : nombre demandé dans la limite
  de 10, sinon 5. offset : 0, ou position de la page suivante issue de la consultation
  précédente. Une pagination ne change ni le thème ni les bornes de la recherche.
Ne présente pas une période choisie par toi comme une demande de l'utilisateur.
Si la date d'un échange manque, conserve cette incertitude dans missing_facts.
"""
