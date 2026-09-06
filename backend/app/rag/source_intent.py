"""Detect explicit source-type intent in user queries.

When a user explicitly DIRECTS his question at a category of source ("que dit
la CCN sur…", "que prévoit notre règlement intérieur…"), we restrict the
search to that source type so results are guaranteed to come from the
requested category.

A bare MENTION of a source is NOT an intent: "rupture du contrat de travail",
"si l'employeur a une ccn…" are generic legal questions that need the full
corpus (Code du travail + jurisprudence + CCN). Restricting them was measured
in prod to empty the candidate pool (~3 % of questions). The trigger therefore
requires a directed construction:

- interrogative/prepositional prefix: "que dit/prévoit … <source>",
  "selon <source>", "d'après <source>", "aux termes de <source>",
  "dans <source>" (for documentary sources only);
- or the source followed closely by a content verb: "la CCN prévoit-elle…";
- or a possessive form pointing at the org's own document: "notre RI",
  "mon contrat", "nos accords".

A missed trigger is harmless (full search runs); a false trigger destroys
recall — patterns are biased accordingly.
"""

import re

# Content verbs that mark a question directed at what a source SAYS.
_VERBS = (
    r"(?:dit|disent|pr[ée]voit|pr[ée]voient|pr[ée]cisent?|indiquent?"
    r"|stipulent?|mentionnent?|contient|contiennent|disposent?"
    r"|imposent?|interdit|interdisent|autorisent?|encadrent?"
    r"|couvrent?|fixent?)"
)
_DET = r"(?:l['’]\s*|(?:la|le|les|ma|mon|mes|notre|nos|votre|vos|cette|ce|ces|une?)\s+)"


def _directed(noun: str, allow_dans: bool = False) -> str:
    """Regex firing only when the query is *directed at* the source ``noun``.

    allow_dans: also accept "dans <source>" ("le report des congés dans la
    CCN"). Reserved for documentary sources where this phrasing is
    unambiguous — NOT for "contrat de travail" ("une clause dans le contrat
    de travail est-elle valable ?" is a generic legal question).
    """
    prefixes = rf"que\s+{_VERBS}|selon|d['’]apr[èe]s|aux\s+termes\s+d[eu]"
    if allow_dans:
        prefixes += r"|dans"
    return (
        rf"(?:\b(?:{prefixes})\s+(?:{_DET})?{noun}"
        rf"|\b{noun}(?:\s+\S+){{0,3}}?\s+{_VERBS})"
    )


# Each entry: (compiled regex, list of source_types, needs_org_filter)
# needs_org_filter: True = org-specific docs, False = common docs
_INTENT_PATTERNS: list[tuple[re.Pattern, list[str], bool]] = [
    # CCN / Convention collective
    (
        re.compile(
            _directed(r"(?:ccn|convention\s+collective)", allow_dans=True)
            + r"|\b(?:ma|notre|votre)\s+convention\b",
            re.IGNORECASE,
        ),
        ["convention_collective_nationale", "accord_branche"],
        False,
    ),
    # Accord d'entreprise
    (
        re.compile(
            _directed(r"accords?\s+(?:collectifs?\s+)?d['’]entreprise", allow_dans=True)
            + r"|\bnos\s+accords\b|\bnotre\s+accord\b",
            re.IGNORECASE,
        ),
        ["accord_entreprise", "accord_performance_collective"],
        True,
    ),
    # Règlement intérieur
    (
        re.compile(
            _directed(r"r[eè]glement\s+int[eé]rieur", allow_dans=True)
            + r"|\b(?:notre|mon|votre)\s+(?:ri\b|r[eè]glement\s+int[eé]rieur)",
            re.IGNORECASE,
        ),
        ["reglement_interieur"],
        True,
    ),
    # Contrat de travail — possessif ou dirigé uniquement ; jamais "dans"
    # ni la simple mention ("rupture du contrat de travail" = question
    # générale, pas une question sur le document contrat de l'org).
    (
        re.compile(
            _directed(r"contrat\s+de\s+travail")
            + r"|\b(?:mon|notre|votre|son)\s+contrat\s+de\s+travail\b"
            + r"|\bmon\s+contrat\b",
            re.IGNORECASE,
        ),
        ["contrat_travail"],
        True,
    ),
    # Code du travail
    (
        re.compile(
            _directed(r"code\s+du\s+travail", allow_dans=True),
            re.IGNORECASE,
        ),
        ["code_travail", "code_travail_reglementaire"],
        False,
    ),
    # Jurisprudence — dirigé ("que dit la jurisprudence", "des arrêts sur…").
    # La simple mention ("la Cour de cassation a déjà jugé…") ne déclenche
    # plus : la question a souvent aussi besoin des textes.
    (
        re.compile(
            _directed(r"(?:jurisprudence|cour\s+de\s+cassation)")
            + r"|\bjurisprudences?\s+(?:r[ée]cente?s?\s+)?"
            + r"(?:sur|concernant|relative?s?|en\s+mati[èe]re|à\s+propos)"
            + r"|\barr[eê]ts?\s+(?:r[ée]cents?\s+)?"
            + r"(?:sur|concernant|relatifs?|en\s+mati[èe]re|à\s+propos)",
            re.IGNORECASE,
        ),
        [
            "arret_cour_cassation",
            "arret_cour_appel",
            "arret_conseil_etat",
            "decision_conseil_constitutionnel",
        ],
        False,
    ),
    # BOSS — Bulletin officiel de la Sécurité sociale (doctrine cotisations).
    # « boss » est aussi de l'argot pour « le manager » : on n'accepte donc que
    # des formes dirigées non ambiguës ("que dit le BOSS", "selon le BOSS", "le
    # BOSS prévoit…") ou le nom complet — jamais la forme possessive ("mon boss
    # dit"). Document commun → pas de filtre org.
    (
        re.compile(
            r"(?:que\s+" + _VERBS + r"|selon|d['’]apr[èe]s|aux\s+termes\s+d[eu]|dans)"
            r"\s+(?:le\s+|du\s+)?boss\b"
            r"|\b(?:le|du)\s+boss\s+(?:\S+\s+){0,2}?" + _VERBS
            + r"|\bbulletin\s+officiel\s+de\s+la\s+s[ée]curit[ée]\s+sociale\b",
            re.IGNORECASE,
        ),
        ["boss"],
        False,
    ),
    # DUE / Engagement unilatéral
    (
        re.compile(
            _directed(r"(?:d[eé]cision\s+unilat[eé]rale|engagement\s+unilat[eé]ral|due)")
            + r"|\b(?:notre|votre)\s+due\b",
            re.IGNORECASE,
        ),
        ["engagement_unilateral"],
        True,
    ),
    # Usage d'entreprise
    (
        re.compile(
            _directed(r"usages?\s+d['’]entreprise")
            + r"|\bnos\s+usages\b",
            re.IGNORECASE,
        ),
        ["usage_entreprise"],
        True,
    ),
]


# Corpus labels are shared by source routing and exact-reference resolution.
CODE_SOURCE_LABELS: dict[str, list[str]] = {
    r"code\s+du\s+travail": ["code_travail", "code_travail_reglementaire"],
    r"code\s+de\s+la\s+s[ée]curit[ée]\s+sociale": [
        "code_securite_sociale", "code_securite_sociale_reglementaire",
    ],
    r"code\s+civil": ["code_civil", "code_civil_reglementaire"],
    r"code\s+p[ée]nal": ["code_penal"],
    r"code\s+de\s+commerce": ["code_commerce", "code_commerce_reglementaire"],
    r"code\s+de\s+l['’]action\s+sociale(?:\s+et\s+des\s+familles)?": [
        "code_action_sociale", "code_action_sociale_reglementaire",
    ],
    r"code\s+de\s+la\s+sant[ée]\s+publique": [
        "code_sante_publique", "code_sante_publique_reglementaire",
    ],
    r"code\s+mon[ée]taire\s+et\s+financier": [
        "code_monetaire_financier", "code_monetaire_financier_reglementaire",
    ],
    r"code\s+g[ée]n[ée]ral\s+des\s+imp[ôo]ts": [
        "code_general_impots", "code_general_impots_reglementaire",
    ],
}
for _label, _types in CODE_SOURCE_LABELS.items():
    if "code_travail" not in _types:
        _INTENT_PATTERNS.append((re.compile(_directed(_label, True), re.I), _types, False))

_SOURCE_LABELS = list(CODE_SOURCE_LABELS.items()) + [
    (r"\b(?:ccn|convention\s+collective)\b", ["convention_collective_nationale", "accord_branche"]),
    (r"\baccords?\s+d['’]entreprise\b", ["accord_entreprise", "accord_performance_collective"]),
    (r"\b(?:jurisprudence|arrêts?)\b", [
        "arret_cour_cassation", "arret_cour_appel", "arret_conseil_etat",
        "decision_conseil_constitutionnel",
    ]),
    (r"\bboss\b", ["boss"]),
    (r"\br[èe]glement\s+int[ée]rieur\b", ["reglement_interieur"]),
    (r"\bcontrat(?:\s+de\s+travail)?\b", ["contrat_travail"]),
    (r"\b(?:due|d[ée]cision\s+unilat[ée]rale)\b", ["engagement_unilateral"]),
]
_NEGATED_SEARCH = re.compile(
    r"\b(?:ne\s+(?:\w+\s+){0,3}(?:cherche|recherche|utilise|consulte)\w*\s+pas"
    r"|ignore|exclus|exclure|sans\s+(?:consulter|utiliser|chercher\s+dans))\b", re.I,
)


def source_clauses(query: str) -> list[str]:
    return re.split(r"[,;!?\n]|\bmais\b", query, flags=re.I)


def mentioned_source_types(query: str) -> list[str]:
    return list(dict.fromkeys(
        st for label, types in _SOURCE_LABELS if re.search(label, query, re.I) for st in types
    ))


def detect_source_exclusions(query: str) -> list[str]:
    return list(dict.fromkeys(
        st for clause in source_clauses(query) if _NEGATED_SEARCH.search(clause)
        for st in mentioned_source_types(clause)
    ))


def detect_exclusive_sources(query: str) -> list[str]:
    result = []
    for clause in source_clauses(query):
        if _NEGATED_SEARCH.search(clause):
            continue
        for label, types in _SOURCE_LABELS:
            for match in re.finditer(label, clause, re.I):
                before = clause[:match.start()]
                after = clause[match.end():]
                if re.search(
                    rf"\b(?:uniquement|exclusivement|seulement)\s+"
                    rf"(?:(?:dans|selon)\s+)?(?:{_DET})?$", before, re.I,
                ) or re.match(r"\s+(?:uniquement|exclusivement|seulement)\b", after, re.I):
                    result.extend(types)
    return list(dict.fromkeys(result))


def detect_source_intent(query: str) -> list[tuple[list[str], bool]]:
    """Detect explicit source-type mentions in the query.

    Returns list of (source_types, needs_org_filter) tuples for each match.
    Empty list if no explicit source is mentioned.
    """
    query = " ; ".join(c for c in source_clauses(query) if not _NEGATED_SEARCH.search(c))
    matches = []
    for pattern, source_types, needs_org in _INTENT_PATTERNS:
        if pattern.search(query):
            matches.append((source_types, needs_org))
    if re.search(r"\b(?:compare\w*|comparaison|diff[ée]rence|uniquement|exclusivement|seulement)\b", query, re.I):
        for source_type in mentioned_source_types(query):
            if not any(source_type in types for types, _ in matches):
                matches.append(([source_type], source_type in {
                    "accord_entreprise", "accord_performance_collective", "contrat_travail",
                    "reglement_interieur", "engagement_unilateral",
                }))
    return matches
