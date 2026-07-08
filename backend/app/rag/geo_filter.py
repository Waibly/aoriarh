"""Détection des textes juridiques *spécifiques à un territoire* (outre-mer,
collectivités à statut particulier).

Contexte : un texte propre à un territoire ultramarin (ex. un décret d'adaptation
« pour Mayotte ») peut être sémantiquement très proche d'une question nationale
et remonter en tête du reranker, alors qu'il est hors-sujet pour la très grande
majorité des organisations (métropole). On le rétrograde donc au reranking.

Choix v1 (cf. décision produit 2026-07) : on rétrograde TOUJOURS les textes
territorialement spécifiques, sans tenir compte de la localisation de l'org
(champ inexistant à ce jour). Les organisations réellement ultramarines sont un
cas particulier qui sera traité plus tard via un attribut de territoire.

La détection porte sur le CONTENU du chunk (et le titre), pas seulement le titre :
le décret fautif observé en prod (2026-82) n'avait « Mayotte » que dans son corps.
"""

# Noms de territoires sans ambiguïté lexicale. « Réunion » (l'île) est
# volontairement EXCLU : le mot « réunion » est omniprésent en droit du travail
# (« réunion du CSE », « réunion des délégués »…) et générerait des faux positifs.
_TERRITORIES = (
    "mayotte",
    "guadeloupe",
    "martinique",
    "guyane",
    "saint-barthélemy",
    "saint-barthelemy",
    "saint-martin",
    "saint-pierre-et-miquelon",
    "nouvelle-calédonie",
    "nouvelle-caledonie",
    "polynésie",
    "polynesie",
    "wallis-et-futuna",
    "wallis et futuna",
)

# Formules qui trahissent une portée territoriale RESTREINTE (par opposition à une
# simple mention incidente). Le placeholder {t} est remplacé par chaque territoire.
_RESTRICTION_CUES = (
    "applicable à {t}",
    "applicables à {t}",
    "s'applique à {t}",
    "s'appliquent à {t}",
    "propre à {t}",
    "propres à {t}",
    "particulières à {t}",
    "en vigueur applicable à {t}",
    # cues non liés au territoire mais typiques d'un texte d'adaptation locale ;
    # ils ne comptent que si un territoire est déjà présent (branche n == 1).
    "adaptations suivantes",
    "à l'exception de son",
)


def is_territorial_specific(text: str, doc_name: str | None = None) -> bool:
    """Retourne True si le texte est propre à un territoire ultramarin donné.

    Heuristique volontairement conservatrice pour éviter de pénaliser un texte
    NATIONAL qui ne fait que mentionner un territoire :
    - un territoire cité ≥ 2 fois → spécifique ;
    - cité 1 fois mais avec une formule de restriction → spécifique ;
    - ≥ 3 territoires distincts cités → énumération d'extension nationale, NON
      spécifique (ex. « le présent décret est applicable à Mayotte, à Saint-Martin
      et à Saint-Barthélemy »).
    """
    hay = f"{doc_name or ''}\n{text or ''}".lower()

    matched = [t for t in _TERRITORIES if t in hay]
    if not matched:
        return False
    # Énumération de plusieurs territoires = clause d'extension d'un texte
    # national, pas une adaptation propre à un territoire.
    if len(set(matched)) >= 3:
        return False

    for terr in matched:
        if hay.count(terr) >= 2:
            return True
        for cue in _RESTRICTION_CUES:
            if cue.format(t=terr) in hay:
                return True
    return False
