"""Input-side availability of date parameters; never inspect or repair generated plans."""

import re

# Recognise user-supplied calendar/relative references, including a delegated date
# ("depuis la date du contrat"). An assistant's citations cannot authorise a filter.
_USER_TIME_REFERENCE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}\b|"
    r"\b(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|"
    r"novembre|décembre|depuis|entre|avant|après|jusqu|hier|demain|aujourd|"
    r"since|until|between|before|after|yesterday|tomorrow|today)\b|"
    r"\b(?:ces?|cette|derni[èe]res?|prochaines?|last|next|past)\s+"
    r"(?:\d+\s+)?(?:jours?|semaines?|mois|ans?|années?|days?|weeks?|months?|years?)\b|"
    r"\b\d+\s+(?:derniers?|dernières?)\s+(?:jours?|semaines?|mois|ans?|années?)\b",
    re.IGNORECASE,
)


def user_period_parameters_available(query: str, history=None) -> bool:
    user_texts = [query]
    if isinstance(history, list):
        user_texts.extend(item.get("content", "") for item in history
                          if isinstance(item, dict) and item.get("role") == "user")
    return any(_USER_TIME_REFERENCE.search(text) for text in user_texts if isinstance(text, str))


def constrain_period_parameters(
    schema: dict, *, available: bool, legal_search_type: str | None = None,
) -> None:
    """Constrain the generation schema before calling the model, without rewriting output."""
    if available:
        return
    definitions = schema["$defs"]
    search = definitions[legal_search_type] if legal_search_type else schema
    search["properties"]["decision_period"] = {"type": "null"}
    chronology = definitions["ChronologyRequest"]["properties"]
    chronology["date_from"] = {"type": "null"}
    chronology["date_to"] = {"type": "null"}
    chronology["period_basis"] = {"type": "string", "enum": ["none"]}
