"""Detect explicit source-type intent in user queries.

When a user explicitly names a category of source ("la CCN", "le Code du travail",
"notre règlement intérieur"), we restrict the search to that source type so results
are guaranteed to come from the requested category.

This is intent-driven, not speculative: we only act when the user names the source.
"""

import re

# Each entry: (compiled regex, list of source_types, needs_org_filter)
# needs_org_filter: True = org-specific docs, False = common docs
_INTENT_PATTERNS: list[tuple[re.Pattern, list[str], bool]] = [
    # CCN / Convention collective
    (
        re.compile(
            r"\b(?:ccn|convention\s+collective|ma\s+convention|notre\s+convention"
            r"|votre\s+convention|la\s+convention)\b",
            re.IGNORECASE,
        ),
        ["convention_collective_nationale", "accord_branche"],
        False,
    ),
    # Accord d'entreprise
    (
        re.compile(
            r"\b(?:accord\s+d['\u2019]entreprise|nos\s+accords|notre\s+accord"
            r"|accord\s+interne|accords?\s+collectifs?\s+d['\u2019]entreprise)\b",
            re.IGNORECASE,
        ),
        ["accord_entreprise", "accord_performance_collective"],
        True,
    ),
    # Règlement intérieur
    (
        re.compile(
            r"\b(?:r[eè]glement\s+int[eé]rieur|notre\s+ri\b|le\s+ri\b|mon\s+ri\b)\b",
            re.IGNORECASE,
        ),
        ["reglement_interieur"],
        True,
    ),
    # Contrat de travail
    (
        re.compile(
            r"\b(?:contrat\s+de\s+travail|mon\s+contrat|notre\s+contrat"
            r"|le\s+contrat)\b",
            re.IGNORECASE,
        ),
        ["contrat_travail"],
        True,
    ),
    # Code du travail
    (
        re.compile(
            r"\b(?:code\s+du\s+travail)\b",
            re.IGNORECASE,
        ),
        ["code_travail", "code_travail_reglementaire"],
        False,
    ),
    # Jurisprudence — "arrêt" seul est exclu car il matche "arrêt maladie"
    (
        re.compile(
            r"\b(?:jurisprudence|cour\s+de\s+cassation|cassation"
            r"|arr[eê]ts?\s+(?:de\s+)?(?:la\s+)?(?:cour|cassation|conseil)"
            r"|cour\s+d['\u2019]appel)\b",
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
    # DUE / Engagement unilatéral
    (
        re.compile(
            r"\b(?:due|d[eé]cision\s+unilat[eé]rale|engagement\s+unilat[eé]ral)\b",
            re.IGNORECASE,
        ),
        ["engagement_unilateral"],
        True,
    ),
    # Usage d'entreprise
    (
        re.compile(
            r"\b(?:usage\s+d['\u2019]entreprise|nos\s+usages|un\s+usage)\b",
            re.IGNORECASE,
        ),
        ["usage_entreprise"],
        True,
    ),
]


def detect_source_intent(query: str) -> list[tuple[list[str], bool]]:
    """Detect explicit source-type mentions in the query.

    Returns list of (source_types, needs_org_filter) tuples for each match.
    Empty list if no explicit source is mentioned.
    """
    matches = []
    for pattern, source_types, needs_org in _INTENT_PATTERNS:
        if pattern.search(query):
            matches.append((source_types, needs_org))
    return matches
