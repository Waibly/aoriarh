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
    jurisdiction: str | None = Field(
        max_length=100,
        description=(
            "Nom de la juridiction à filtrer dans le catalogue, par exemple Cour de cassation, "
            "Cour d'appel de Paris, Conseil d'État ou Conseil constitutionnel. "
            "Jamais un pays (France), un ordre juridique ou une branche du droit. "
            "Null si source_types suffit à désigner la juridiction demandée."
        ),
    )
    chamber: str | None = Field(
        max_length=100,
        description=(
            "Chambre demandée explicitement ou conservée depuis l'historique, "
            "par exemple sociale ou criminelle ; sinon null."
        ),
    )
    topic: str | None = Field(
        max_length=1000,
        description=(
            "Sujet concret à rechercher. Null pour une liste chronologique d'une "
            "chambre précise sans thème particulier, ou explicitement toutes matières. "
            "Pour une veille générale AORIA RH sans autre périmètre : droit du travail, "
            "relations employeur-salarié et protection sociale. Jurisprudence, arrêts "
            "et décisions sont des types de sources, pas des thèmes."
        ),
    )
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
- jurisdiction : nom de la juridiction, jamais le pays « France » ni une branche du droit.
  Ce filtre porte sur le nom stocké (ex. « Cour de cassation », « Cour d'appel de Paris »).
  Lorsque source_types désigne déjà la juridiction demandée, laisse jurisdiction=null ;
  arret_cour_cassation suffit pour la Cour de cassation. Pour une cour d'appel particulière,
  indique son nom dans jurisdiction en plus de source_types=["arret_cour_appel"].
- chamber : chambre explicitement demandée ou conservée depuis l'historique, sinon null.
  « chambre sociale » donne chamber="sociale". Une veille RH générale ne se limite pas
  automatiquement à cette chambre : d'autres juridictions peuvent traiter de questions RH.
- topic : sujet concret demandé, ou null pour une liste chronologique d'une chambre précise
  sans thème particulier, ou explicitement toutes matières. « décrets », « jurisprudence », « arrêts »
  et « décisions » sont des types de sources, pas des thèmes de recherche.
  Pour une veille générale AORIA RH sans autre périmètre explicite ou hérité, utilise
  topic="droit du travail, relations employeur-salarié et protection sociale" et conserve
  ce périmètre RH dans la question de recherche, y compris si seule la Cour de cassation
  est précisée. La procédure pénale générale ne fait pas
  partie de cette veille. Respecte toutefois une demande explicite de pénal du travail,
  d'une autre matière ou de toutes les chambres : ne remplace pas son périmètre par défaut.
  Pour « liste des arrêts de la chambre sociale en septembre », utilise
  source_types=["arret_cour_cassation"], jurisdiction=null, chamber="sociale", topic=null :
  l'intérêt RH demandé dans la présentation ne doit pas restreindre la liste par un thème.
  Pour « arrêts de la chambre sociale sur les congés payés », topic="congés payés".
- order : newest par défaut, oldest si demandé. limit : nombre demandé dans la limite
  de 10, sinon 5. offset : 0, ou position de la page suivante issue de la consultation
  précédente. Une pagination ne change ni le thème ni les bornes de la recherche.
Ne présente pas une période choisie par toi comme une demande de l'utilisateur.
Si la date d'un échange manque, conserve cette incertitude dans missing_facts.
"""
