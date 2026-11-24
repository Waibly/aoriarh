"""Calendar facts computed in code for the dates a question mentions.

The writer model miscounts durations ("plus de 3 mois de présence" between
1 September and 24 November). Elapsed durations, period ends and weekdays are
computed here and handed to it as established facts: it applies the legal
rule, it no longer counts. Only explicit dates are read; nothing is inferred.
"""

import datetime
import re

_MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]
_MONTH_INDEX = {name: i + 1 for i, name in enumerate(_MONTHS)}
_MONTH_INDEX.update({"fevrier": 2, "aout": 8, "decembre": 12})
_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_NUMBER_WORDS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "douze": 12,
    "quinze": 15,
    "dix-huit": 18,
    "vingt-quatre": 24,
    "trente": 30,
}
_MONTH_ALT = "|".join(sorted(_MONTH_INDEX, key=len, reverse=True))
_TEXT_DATE = re.compile(
    rf"\b(?P<day>1er|premier|[0-3]?\d)\s+(?P<month>{_MONTH_ALT})(?:\s+(?P<year>(?:19|20)\d\d))?\b",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(
    r"\b(?P<day>[0-3]?\d)[/.-](?P<month>[01]?\d)[/.-](?P<year>(?:19|20)?\d\d)\b"
)
_NUMBER_ALT = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_DURATION = re.compile(
    rf"\b(?P<n>\d{{1,3}}|{_NUMBER_ALT})\s+(?P<unit>jours?|semaines?|mois|ans?|années?)\b",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)

MAX_DATES = 6
MAX_DURATIONS = 4


def format_date(d: datetime.date) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return f"{_WEEKDAYS[d.weekday()]} {day} {_MONTHS[d.month - 1]} {d.year}"


def add_months(d: datetime.date, months: int) -> datetime.date:
    """Same day N months later, clamped to the month's last day (31/01 + 1 mois = 28/02)."""
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    last = (datetime.date(year + month // 12, month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(d.day, last))


def elapsed(start: datetime.date, end: datetime.date) -> tuple[int, int, int]:
    """Whole years, months and days from start to end (start <= end)."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if add_months(start, months) > end:
        months -= 1
    days = (end - add_months(start, months)).days
    return months // 12, months % 12, days


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def format_elapsed(start: datetime.date, end: datetime.date) -> str:
    years, months, days = elapsed(start, end)
    parts = []
    if years:
        parts.append(_plural(years, "an"))
    if months:
        parts.append(f"{months} mois")
    if days or not parts:
        parts.append(_plural(days, "jour"))
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " et " + parts[-1]
    total_months = years * 12 + months
    if total_months == 0:
        bound = ", soit moins d'un mois"
    elif total_months < 24:
        bound = f", soit {'exactement' if days == 0 else 'plus de'} {total_months} mois" + (
            "" if days == 0 else f" et moins de {total_months + 1} mois"
        )
    else:
        bound = ""
    return f"{text} ({_plural((end - start).days, 'jour')} calendaires{bound})"


def _year(raw: str | None, today: datetime.date) -> tuple[int, bool]:
    if raw is None:
        return today.year, True
    year = int(raw)
    return (year + 2000 if year < 100 else year), False


def extract_dates(text: str, today: datetime.date) -> list[tuple[datetime.date, bool]]:
    """Explicit dates in order of appearance, with a flag when the year was assumed."""
    found: list[tuple[int, datetime.date, bool]] = []
    for match in _TEXT_DATE.finditer(text):
        raw_day = match["day"].lower()
        day = 1 if raw_day in ("1er", "premier") else int(raw_day)
        year, assumed = _year(match["year"], today)
        try:
            found.append(
                (
                    match.start(),
                    datetime.date(year, _MONTH_INDEX[match["month"].lower()], day),
                    assumed,
                )
            )
        except ValueError:
            continue
    for match in _NUMERIC_DATE.finditer(text):
        year, _ = _year(match["year"], today)
        try:
            found.append(
                (match.start(), datetime.date(year, int(match["month"]), int(match["day"])), False)
            )
        except ValueError:
            continue
    result: list[tuple[datetime.date, bool]] = []
    for _, d, assumed in sorted(found, key=lambda item: item[0]):
        if all(d != seen for seen, _ in result):
            result.append((d, assumed))
    return result[:MAX_DATES]


def extract_durations(text: str) -> list[tuple[int, str]]:
    """Durations in months or days ("2 mois", "deux semaines" -> (14, "jours"))."""
    result: list[tuple[int, str]] = []
    for match in _DURATION.finditer(text):
        raw = match["n"].lower()
        n = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
        unit = match["unit"].lower()
        if unit.startswith("an") or unit.startswith("ann"):
            item = (n * 12, "mois")
        elif unit.startswith("semaine"):
            item = (n * 7, "jours")
        elif unit == "mois":
            item = (n, "mois")
        else:
            item = (n, "jours")
        if 0 < item[0] <= 600 and item not in result:
            result.append(item)
    return result[:MAX_DURATIONS]


def _period_line(start: datetime.date, n: int, unit: str) -> str:
    if unit == "mois":
        later = add_months(start, n)
        label = f"{n} mois" if n % 12 else _plural(n // 12, "an")
        if later.day != start.day:  # 31/01 + 1 mois: no same day, the period ends with February
            return (
                f"- {label} à compter du {format_date(start)} : le mois d'arrivée n'a pas de "
                f"{start.day} ; une période de {label} commençant ce jour s'achève le "
                f"{format_date(later)} au soir."
            )
    else:
        later = start + datetime.timedelta(days=n)
        label = _plural(n, "jour")
    last_day = later - datetime.timedelta(days=1)
    return (
        f"- {label} à compter du {format_date(start)} : même quantième atteint le "
        f"{format_date(later)} ; une période de {label} commençant ce jour "
        f"s'achève le {format_date(last_day)} au soir."
    )


def date_facts_block(texts: list[str | None], today: datetime.date | None = None) -> str | None:
    """Computed calendar block for the generation prompt, or None without explicit dates."""
    today = today or datetime.date.today()
    text = "\n".join(t for t in texts if t)
    dates = extract_dates(text, today)
    weekdays = [w.lower() for w in _WEEKDAY.findall(text)]
    if not dates and not weekdays:
        return None
    lines = [f"- Aujourd'hui : {format_date(today)}."]
    for d, assumed in dates:
        note = f" (année non précisée : {d.year} retenue)" if assumed else ""
        if d <= today:
            lines.append(f"- Du {format_date(d)}{note} à aujourd'hui : {format_elapsed(d, today)}.")
        else:
            lines.append(f"- D'aujourd'hui au {format_date(d)}{note} : {format_elapsed(today, d)}.")
    ordered = sorted({d for d, _ in dates})
    for start, end in zip(ordered, ordered[1:]):
        if end != today and start != today:
            lines.append(
                f"- Du {format_date(start)} au {format_date(end)} : {format_elapsed(start, end)}."
            )
    durations = extract_durations(text)
    for d, _ in dates[:3]:
        for n, unit in durations:
            lines.append(_period_line(d, n, unit))
    for name in dict.fromkeys(weekdays):
        delta = (_WEEKDAYS.index(name) - today.weekday()) % 7 or 7
        lines.append(f"- Prochain {name} : {format_date(today + datetime.timedelta(days=delta))}.")
    return (
        "## Repères de calendrier calculés par le système\n\n"
        "Ces durées et dates sont calculées exactement à partir des dates de la question. "
        "Reprends-les telles quelles et ne recompte pas de tête : applique la règle "
        "juridique au bon chiffre (palier d'ancienneté, délai, échéance). Elles ne "
        "tiennent pas compte des suspensions ni des règles de computation propres à un "
        "texte (jours ouvrables, report au jour ouvrable suivant).\n\n" + "\n".join(lines)
    )
