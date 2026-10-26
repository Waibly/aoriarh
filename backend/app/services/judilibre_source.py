"""Preserve official documentary material alongside the original decision body."""


def official_summaries(raw: dict) -> list[str]:
    entries = raw.get("titlesAndSummaries")
    if entries is None:
        entries = []
    if (raw.get("summary") is not None and not isinstance(raw["summary"], str)
            or not isinstance(entries, list)):
        raise ValueError("judilibre_invalid_official_summary_structure")
    values = [raw.get("summary")]
    for item in entries:
        if not isinstance(item, dict) or (item.get("summary") is not None
                                         and not isinstance(item["summary"], str)):
            raise ValueError("judilibre_invalid_official_summary_structure")
        values.append(item.get("summary"))
    # Duplicate fields describe the same source. Do not rewrite their contents.
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def render_judilibre_source(raw: dict) -> str:
    body = raw.get("text")
    if not isinstance(body, str) or not body:
        raise ValueError("judilibre_missing_decision_text")
    sections = []
    for item in raw.get("titlesAndSummaries") or []:
        if not isinstance(item, dict):
            continue
        titles = item.get("titles") or []
        if titles:
            if not isinstance(titles, list) or not all(isinstance(title, str) for title in titles):
                raise ValueError("judilibre_invalid_official_titles")
            sections.append("Titres officiels\n" + "\n".join(titles))
    sections.extend("Sommaire officiel\n" + summary for summary in official_summaries(raw))
    return "\n\n".join([*sections, "Texte de la décision\n" + body]) if sections else body
