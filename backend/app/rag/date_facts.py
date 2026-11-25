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


def format_date(d: datetime.date, weekday: bool = True) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    text = f"{day} {_MONTHS[d.month - 1]} {d.year}"
    return f"{_WEEKDAYS[d.weekday()]} {text}" if weekday else text


def plain_date(d: datetime.date) -> str:
    """A starting date, without weekday: the model mixed up start and end weekdays."""
    return format_date(d, weekday=False)


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
                f"- {label} à compter du {plain_date(start)} : le mois d'arrivée n'a pas de "
                f"{start.day} ; une période de {label} commençant ce jour s'achève le "
                f"{format_date(later)} au soir."
            )
    else:
        later = start + datetime.timedelta(days=n)
        label = _plural(n, "jour")
    last_day = later - datetime.timedelta(days=1)
    return (
        f"- {label} à compter du {plain_date(start)} : même quantième atteint le "
        f"{format_date(later)} ; une période de {label} commençant ce jour "
        f"s'achève le {format_date(last_day)} au soir."
    )


_DEADLINES = [
    (8, "jours"),
    (15, "jours"),
    (1, "mois"),
    (2, "mois"),
    (3, "mois"),
    (6, "mois"),
    (12, "mois"),
    (24, "mois"),
    (36, "mois"),
    (60, "mois"),
]


def _deadline_line(start: datetime.date, today: datetime.date) -> str:
    """Usual legal deadlines from a date, split into expired and still running today."""
    expired, running = [], []
    for n, unit in _DEADLINES:
        if unit == "mois":
            end = add_months(start, n)
            label = f"{n} mois" if n % 12 else _plural(n // 12, "an")
        else:
            end = start + datetime.timedelta(days=n)
            label = f"{n} jours"
        item = f"{label} (le {format_date(end)})"
        (expired if end < today else running).append(item)
    parts = [
        f"- Délais courant à compter du {plain_date(start)} (délai en mois : jour du même "
        "quantième ; délai en jours : le jour de départ ne compte pas ; avant tout report "
        "de samedi, dimanche ou jour férié)."
    ]
    if expired:
        parts.append("  DÉJÀ EXPIRÉS aujourd'hui : " + " ; ".join(expired) + ".")
    if running:
        parts.append("  PAS ENCORE EXPIRÉS aujourd'hui : " + " ; ".join(running) + ".")
    return "\n".join(parts)


def _easter(year: int) -> datetime.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def public_holidays(year: int) -> set[datetime.date]:
    """The 11 national public holidays of metropolitan France."""
    easter = _easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    days = {datetime.date(year, m, d) for m, d in fixed}
    days |= {easter + datetime.timedelta(days=n) for n in (1, 39, 50)}
    return days


def working_days_after(start: datetime.date, count: int) -> list[datetime.date]:
    """The jours ouvrables following start (Monday to Saturday, public holidays excluded)."""
    result, day = [], start
    while len(result) < count:
        day += datetime.timedelta(days=1)
        if day.weekday() != 6 and day not in public_holidays(day.year):
            result.append(day)
    return result


def _working_days_line(start: datetime.date) -> str:
    days = working_days_after(start, 6)
    listed = " ; ".join(f"{n}e : {format_date(d)}" for n, d in enumerate(days, start=1))
    return (
        f"- Jours ouvrables suivant le {plain_date(start)} (lundi au samedi, sans les "
        f"dimanches ni les jours fériés nationaux ; le jour de départ ne compte pas) : "
        f"{listed.replace('1e :', '1er :', 1)}."
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
            lines.append(f"- Du {plain_date(d)}{note} à aujourd'hui : {format_elapsed(d, today)}.")
        else:
            lines.append(f"- D'aujourd'hui au {format_date(d)}{note} : {format_elapsed(today, d)}.")
    ordered = sorted({d for d, _ in dates})
    for start, end in zip(ordered, ordered[1:]):
        if end != today and start != today:
            lines.append(
                f"- Du {plain_date(start)} au {plain_date(end)} : {format_elapsed(start, end)}."
            )
    durations = extract_durations(text)
    for d, _ in dates[:3]:
        for n, unit in durations:
            lines.append(_period_line(d, n, unit))
    for d, _ in dates[:2]:
        lines.append(_deadline_line(d, today))
        if abs((d - today).days) <= 60:
            lines.append(_working_days_line(d))
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


def expired_reminder(texts: list[str | None], today: datetime.date | None = None) -> str | None:
    """One line placed right after the question: time already elapsed since each past date."""
    today = today or datetime.date.today()
    text = "\n".join(t for t in texts if t)
    items = [
        f"depuis le {plain_date(start)} : {format_elapsed(start, today)} déjà écoulés"
        for start, _ in extract_dates(text, today)[:3]
        if start < today
    ]
    if not items:
        return None
    return (
        f"(Repère calculé : nous sommes le {format_date(today)} ; "
        + " ; ".join(items)
        + ". Situe chaque délai ou seuil par rapport à ces durées avant d'écrire ton verdict.)"
    )
