"""Literal social-case references, with source offsets and no legal-status inference."""

import re
from datetime import date

CASE_REFERENCES_CONTEXT_LIMIT = 20


def case_reference_context_metadata(numbers: list[str] | None) -> dict:
    """Describe large joined-case sets without repeating hundreds of IDs per passage.

    The complete list remains in source/index metadata and exact-ID lookup.
    Original passage text and model outputs are never changed.
    """
    if numbers is None:
        return {}
    if len(numbers) <= CASE_REFERENCES_CONTEXT_LIMIT:
        return {"numero_pourvois": numbers}
    return {"nombre_references_pourvoi_renseignees": len(numbers)}


MONTHS = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}
_REFERENCE = re.compile(
    r"\b(?:soc\.|chambre\s+sociale)\s*,?\s*"
    r"(?P<day>\d{1,2})(?:er)?\s+(?P<month>" + "|".join(MONTHS) + r")\s+"
    r"(?P<year>(?:19|20)\d{2})\s*,?\s*"
    r"(?:(?:pourvois?\s+)?n[°ºo]\s*[sˢ]?\s*)?"
    r"(?P<number>\d{2}\s*[-‑–]\s*\d{2}[.\s]?\d{3})(?!\d)",
    re.IGNORECASE,
)


def social_case_references(text: str) -> list[dict]:
    result = []
    for match in _REFERENCE.finditer(text):
        try:
            day = date(int(match["year"]), MONTHS[match["month"].lower()], int(match["day"]))
        except ValueError:
            continue
        digits = "".join(c for c in match["number"] if c.isdigit())
        result.append(
            {
                "date": day.isoformat(),
                "number": digits[:2] + "-" + digits[2:4] + "." + digits[4:],
                "start": match.start(),
                "end": match.end(),
                "literal": match.group(),
            }
        )
    return result
