"""Publication labels from official Judilibre codes, independently of decision text.

Judilibre codes are canonical metadata. Literal historical sigles from a court
minute are left untouched: before June 2021, P and B had different meanings.
"""

BULLETIN = "Publié au Bulletin"
RAPPORT = "Publié au Rapport annuel (R)"
BULLETIN_RAPPORT = "Publié au Bulletin et au Rapport annuel (B/R)"

PUBLICATION_GUIDANCE = (
    "Pour la jurisprudence de cassation, la sélection B/R indique une portée "
    "jurisprudentielle particulièrement importante et B une sélection au Bulletin. "
    "Apprécier cette information avec la pertinence, la date, l'applicabilité "
    "et l'évolution ultérieure du droit, sans priorité automatique sur un passage pertinent. "
)


def judilibre_publication_label(raw) -> str:
    if not isinstance(raw, list):
        return str(raw)
    if not all(isinstance(code, str) for code in raw):
        raise ValueError("Invalid official publication codes")
    codes = {code.lower() for code in raw}
    if {"b", "r"} <= codes:
        return BULLETIN_RAPPORT
    if "r" in codes:
        return RAPPORT
    return BULLETIN if "b" in codes else "Inédit"


def publication_significance(publication: str | None, source_type: str) -> str | None:
    if source_type != "arret_cour_cassation":
        return None
    if publication in {BULLETIN_RAPPORT, RAPPORT}:
        return (
            "Sélection au Rapport annuel : portée jurisprudentielle particulièrement "
            "importante, à apprécier avec la pertinence, la date et l'applicabilité."
        )
    if publication == BULLETIN:
        return "Sélection au Bulletin pour son intérêt jurisprudentiel."
    return None
