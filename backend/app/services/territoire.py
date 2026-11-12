"""Lieu d'implantation d'une organisation : métropole, droit local ou outre-mer.

Le territoire change le droit applicable (droit local d'Alsace-Moselle,
adaptations outre-mer, droit du travail propre dans le Pacifique). Il est
transmis au moteur comme la CCN pour que la recherche et la rédaction en
tiennent compte sans que l'utilisateur ait à le rappeler.
"""

import re
from enum import StrEnum


class Territoire(StrEnum):
    METROPOLE = "metropole"
    ALSACE_MOSELLE = "alsace_moselle"
    GUADELOUPE = "guadeloupe"
    MARTINIQUE = "martinique"
    GUYANE = "guyane"
    LA_REUNION = "la_reunion"
    MAYOTTE = "mayotte"
    SAINT_PIERRE_MIQUELON = "saint_pierre_miquelon"
    SAINT_BARTHELEMY = "saint_barthelemy"
    SAINT_MARTIN = "saint_martin"
    NOUVELLE_CALEDONIE = "nouvelle_caledonie"
    POLYNESIE = "polynesie"
    WALLIS_FUTUNA = "wallis_futuna"


DEFAULT_TERRITOIRE = Territoire.METROPOLE

TERRITOIRE_LABELS: dict[Territoire, str] = {
    Territoire.METROPOLE: "France métropolitaine",
    Territoire.ALSACE_MOSELLE: "Alsace-Moselle (Bas-Rhin, Haut-Rhin, Moselle)",
    Territoire.GUADELOUPE: "Guadeloupe",
    Territoire.MARTINIQUE: "Martinique",
    Territoire.GUYANE: "Guyane",
    Territoire.LA_REUNION: "La Réunion",
    Territoire.MAYOTTE: "Mayotte",
    Territoire.SAINT_PIERRE_MIQUELON: "Saint-Pierre-et-Miquelon",
    Territoire.SAINT_BARTHELEMY: "Saint-Barthélemy",
    Territoire.SAINT_MARTIN: "Saint-Martin",
    Territoire.NOUVELLE_CALEDONIE: "Nouvelle-Calédonie",
    Territoire.POLYNESIE: "Polynésie française",
    Territoire.WALLIS_FUTUNA: "Wallis-et-Futuna",
}

_OUTRE_MER_CODE_TRAVAIL = {
    Territoire.GUADELOUPE,
    Territoire.MARTINIQUE,
    Territoire.GUYANE,
    Territoire.LA_REUNION,
    Territoire.MAYOTTE,
    Territoire.SAINT_PIERRE_MIQUELON,
    Territoire.SAINT_BARTHELEMY,
    Territoire.SAINT_MARTIN,
}
_DROIT_DU_TRAVAIL_PROPRE = {
    Territoire.NOUVELLE_CALEDONIE,
    Territoire.POLYNESIE,
    Territoire.WALLIS_FUTUNA,
}


_BY_LABEL = {label: territoire for territoire, label in TERRITOIRE_LABELS.items()}


def parse_territoire(value: str | None) -> Territoire:
    """Code stocké ou libellé (contexte d'organisation) → territoire.

    Toute valeur inconnue retombe sur la métropole."""
    if not value:
        return DEFAULT_TERRITOIRE
    if value in _BY_LABEL:
        return _BY_LABEL[value]
    try:
        return Territoire(value)
    except ValueError:
        return DEFAULT_TERRITOIRE


def territoire_label(value: str | None) -> str:
    return TERRITOIRE_LABELS[parse_territoire(value)]


def territoire_instruction(value: str | None) -> str | None:
    """Consigne de rédaction propre au territoire (None pour la métropole)."""
    territoire = parse_territoire(value)
    label = TERRITOIRE_LABELS[territoire]
    if territoire == Territoire.ALSACE_MOSELLE:
        return (
            "L'entreprise relève du droit local d'Alsace-Moselle. Applique le droit "
            "commun, mais vérifie et signale les règles de droit local quand elles "
            "jouent sur la question (jours fériés supplémentaires, maintien de salaire, "
            "régime local d'assurance maladie, repos dominical et jours fériés dans le "
            "commerce…). Si les sources fournies ne couvrent pas le point local, dis-le "
            "au lieu de supposer que le droit commun suffit."
        )
    if territoire in _OUTRE_MER_CODE_TRAVAIL:
        mayotte = (
            " Mayotte connaît de nombreuses adaptations (SMIC propre, régime de "
            "sécurité sociale propre) : ne transpose pas un montant ou un taux de "
            "métropole sans source qui le confirme pour Mayotte."
            if territoire == Territoire.MAYOTTE
            else ""
        )
        return (
            f"Lieu d'implantation de l'entreprise : {label} (outre-mer). Le Code du travail "
            "s'y applique avec les adaptations prévues pour l'outre-mer (livres "
            "« Dispositions relatives à l'outre-mer »). Vérifie et signale ce qui "
            "diffère de la métropole quand la question y touche : jours fériés propres "
            "(commémoration de l'abolition de l'esclavage), exonérations de cotisations "
            "propres à l'outre-mer (LODEOM), organismes de sécurité sociale propres, "
            "accords régionaux. Pour la convention collective, vérifie dans les sources "
            "que son champ d'application territorial couvre ce territoire et signale-le "
            "si tu ne peux pas le vérifier. Si les sources ne disent rien de propre au "
            "territoire sur un point, indique que la règle de droit commun s'applique sauf "
            "adaptation locale non identifiée, sans inventer de règle locale." + mayotte
        )
    if territoire in _DROIT_DU_TRAVAIL_PROPRE:
        return (
            f"Lieu d'implantation de l'entreprise : {label}. Le Code du travail français ne "
            "s'y applique pas : ce territoire a son propre droit du travail et sa propre "
            "protection sociale, que nos sources ne couvrent pas. Dis-le clairement en "
            "tête de réponse, ne présente pas le droit métropolitain comme applicable et "
            "oriente vers les textes et interlocuteurs locaux (inspection du travail "
            "locale, conseil local). Tu peux indiquer la règle métropolitaine seulement "
            "comme point de comparaison, en le précisant."
        )
    return None


# --- Textes conventionnels propres à un territoire ---------------------------
#
# Une convention nationale embarque parfois des accords régionaux (« Martinique
# Accord … relatif à la valeur du point », « prime de vie chère (Guadeloupe) »).
# Ils ne valent que pour leur territoire : une entreprise de métropole ne doit
# pas les recevoir, une entreprise de ce territoire doit les garder. Le titre du
# texte est le seul signal fiable fourni par KALI.

_DOM = sorted(t.value for t in _OUTRE_MER_CODE_TRAVAIL)

_TITLE_PATTERNS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\bMartinique\b", re.I), [Territoire.MARTINIQUE.value]),
    (re.compile(r"\bGuadeloupe\b", re.I), [Territoire.GUADELOUPE.value]),
    (re.compile(r"\bGuyane\b", re.I), [Territoire.GUYANE.value]),
    (re.compile(r"\bMayotte\b", re.I), [Territoire.MAYOTTE.value]),
    # « réunion » minuscule désigne presque toujours une réunion paritaire :
    # seule l'île, écrite avec une majuscule après « la » ou entre parenthèses.
    (re.compile(r"(?:\b[Ll]a\s+|\()R[ée]union\b(?!s)"), [Territoire.LA_REUNION.value]),
    (
        re.compile(r"\bSaint-Pierre-et-Miquelon\b|\bMiquelon\b", re.I),
        [Territoire.SAINT_PIERRE_MIQUELON.value],
    ),
    (re.compile(r"\bSaint-Barth[ée]lemy\b", re.I), [Territoire.SAINT_BARTHELEMY.value]),
    (re.compile(r"\bSaint-Martin\b(?!-)", re.I), [Territoire.SAINT_MARTIN.value]),
    (re.compile(r"\bAntilles\b", re.I), [Territoire.GUADELOUPE.value, Territoire.MARTINIQUE.value]),
    (re.compile(r"\bNouvelle-Cal[ée]donie\b", re.I), [Territoire.NOUVELLE_CALEDONIE.value]),
    (re.compile(r"\bPolyn[ée]sie\b", re.I), [Territoire.POLYNESIE.value]),
    (re.compile(r"\bWallis\b", re.I), [Territoire.WALLIS_FUTUNA.value]),
    (re.compile(r"\bD\.?R?\.?O\.?M\b"), _DOM),
    (re.compile(r"d[ée]partements?\s+(?:et\s+r[ée]gions?\s+)?d'outre-mer", re.I), _DOM),
]


def territoires_from_title(title: str | None) -> list[str]:
    """Codes des territoires nommés dans le titre d'un texte (vide = aucun)."""
    if not title:
        return []
    found: list[str] = []
    for pattern, codes in _TITLE_PATTERNS:
        if pattern.search(title):
            found.extend(c for c in codes if c not in found)
    return sorted(found)


def instrument_territoires(instrument_title: str | None, convention_name: str | None) -> list[str]:
    """Territoires d'un texte rattaché à une convention, s'il lui est propre.

    Une convention elle-même territoriale (banques de la Guadeloupe…) a été
    choisie par l'entreprise : ses textes ne sont jamais restreints."""
    if territoires_from_title(convention_name):
        return []
    return territoires_from_title(instrument_title)


_GENERATED_KALI_PREFIXES = ("CCN ", "Accords de branche — ")


def document_territoires(doc_name: str | None, convention_title: str | None) -> list[str]:
    """Territoires d'un accord publié seul (BOCC), d'après le nom du document.

    Les instantanés KALI (« CCN … », « Accords de branche — … ») sont étiquetés
    texte par texte : leur nom, celui de la convention, n'est pas un signal."""
    if not doc_name or doc_name.startswith(_GENERATED_KALI_PREFIXES):
        return []
    return instrument_territoires(doc_name, convention_title)
