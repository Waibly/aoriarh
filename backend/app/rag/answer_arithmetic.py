"""Check the operations written in a generated answer ("2 850 € × 1/4 × 9,5 = 6 768,75 €").

The writing model may still compute some amounts itself. Each operation it writes is
recomputed exactly; an inexact one is reported so a correction can be appended to the
answer (the streamed text is never rewritten). Anything not read with certainty is
ignored: a false correction would be worse than none.
"""

import re
from decimal import Decimal, InvalidOperation, localcontext

from app.services.case_calculation import CalculationSpec, calculate

_NUMBER = r"\d{1,3}(?:[   ]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_TOKEN = re.compile(
    # A number glued to letters ("T0", "1ère", "35h") is not read as a number.
    rf"(?P<num>(?<![A-Za-zÀ-ÿ\d])(?:{_NUMBER})(?![A-Za-zÀ-ÿ\d]))"
    r"|(?P<op>[×x*÷/+\-−–])|(?P<par>[()])|(?P<pct>%)"
    r"|(?P<word>[A-Za-zÀ-ÿ€'][\wÀ-ÿ€']*)|(?P<space>\s+)|(?P<other>.)"
)
# Units that may sit inside an operation without changing it.
_UNITS = {
    "€",
    "eur",
    "euro",
    "euros",
    "brut",
    "bruts",
    "brute",
    "brutes",
    "net",
    "nets",
    "nette",
    "h",
    "heure",
    "heures",
    "mois",
    "an",
    "ans",
    "année",
    "années",
    "jour",
    "jours",
    "semaine",
    "semaines",
    "mensuel",
    "mensuels",
    "mensuelle",
    "mensuelles",
    "hebdomadaire",
    "hebdomadaires",
    "annuel",
    "annuels",
    "annuelle",
    "annuelles",
}
# "salaire de 2 850 € × 1/4" may hide a factor written in words before it: skip.
_UNSAFE_BEFORE = {"de", "du", "des", "d'", "sur", "par", "le", "la", "les", "un", "une", "l'"}


def _tokens(text: str) -> list[tuple[str, str]]:
    out = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup
        value = match.group()
        if kind == "space":
            continue
        if kind == "word" and value.lower() == "x":
            kind = "op"
        out.append((kind, value))
    return out


def _number(text: str) -> Decimal:
    cleaned = re.sub(r"[   ]", "", text).replace(",", ".")
    return Decimal(cleaned)


def _expression(tokens: list[tuple[str, str]]) -> tuple[str, int] | None:
    """ASCII arithmetic and operator count, or None when the tokens are not pure arithmetic."""
    parts: list[str] = []
    operators = numbers = 0
    for kind, value in tokens:
        if kind == "num":
            parts.append(format(_number(value), "f"))
            numbers += 1
        elif kind == "op":
            parts.append({"×": "*", "x": "*", "÷": "/", "−": "-", "–": "-"}.get(value, value))
            operators += 1
        elif kind == "par":
            parts.append(value)
        elif kind == "pct":
            parts.append("/100")
        elif kind == "word" and value.lower() in _UNITS:
            continue
        else:
            return None
    if numbers < 1:
        return None
    return " ".join(parts), operators


def _evaluate(expression: str) -> Decimal | None:
    try:
        spec = CalculationSpec(
            expression=expression,
            variables=[],
            source_document_ids=[],
            formula_source="answer",
            assumptions=[],
            scenario="answer",
            unit="",
        )
        return Decimal(calculate(spec))
    except (ValueError, ArithmeticError, SyntaxError, InvalidOperation):
        return None


def _left_operand(tokens):
    """Longest arithmetic tail before "=", starting at a safe boundary."""
    start = len(tokens)
    while start > 0:
        kind, value = tokens[start - 1]
        if kind in {"num", "op", "par", "pct"} or (kind == "word" and value.lower() in _UNITS):
            start -= 1
            continue
        break
    if start > 0:
        kind, value = tokens[start - 1]
        if kind == "word" and value.lower() in _UNSAFE_BEFORE:
            return None
    tail = tokens[start:]
    while tail and tail[0][0] == "word":  # A leading unit belongs to the prose before it.
        tail = tail[1:]
    if tail and (tail[0][0] in {"op", "pct"} or tail[0] == ("par", ")")):
        return None  # Its first operand is written in words: not read.
    return tail


def _right_operand(tokens):
    """Arithmetic prefix after "=", or None when the value continues ("9 ans et 6 mois")."""
    end = 0
    while end < len(tokens):
        kind, value = tokens[end]
        if kind in {"num", "op", "par", "pct"} or (kind == "word" and value.lower() in _UNITS):
            end += 1
            continue
        break
    rest = tokens[end:]
    if rest and rest[0][0] == "word" and rest[0][1].lower() == "et":
        return None
    if rest and rest[0] == ("other", ",") and len(rest) > 1 and rest[1][0] == "num":
        return None
    return tokens[:end]


def _decimals(tokens) -> int:
    numbers = [value for kind, value in tokens if kind == "num"]
    if len(numbers) != 1:
        return 2
    _, _, fraction = re.sub(r"[   ]", "", numbers[0]).replace(",", ".").partition(".")
    return len(fraction)


def _display(tokens) -> str:
    text = " ".join(value for _, value in tokens)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"(?<=\d) / (?=\d)", "/", text)
    return re.sub(r"\s+([)%])", r"\1", text)


def french_amount(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 28
        rounded = value.quantize(Decimal("0.01"))
    sign = "-" if rounded < 0 else ""
    integer, _, fraction = format(abs(rounded), "f").partition(".")
    grouped = f"{int(integer):,}".replace(",", " ")
    return f"{sign}{grouped},{fraction}" if fraction.strip("0") else f"{sign}{grouped}"


def _segments(text: str) -> list[str]:
    cleaned = re.sub(r"[*`_]", "", text)
    pieces = []
    for line in cleaned.splitlines():
        if "\\" in line:  # LaTeX: not read.
            continue
        pieces.extend(cell for cell in line.split("|") if "=" in cell)
    return pieces


def find_arithmetic_errors(answer: str, checked: list | None = None) -> list[dict]:
    """Written operations whose stated result is wrong beyond rounding."""
    checked = [] if checked is None else checked
    errors = []
    seen = set()
    for piece in _segments(answer):
        parts = re.split(r"(?<![<>!=])=(?!=)", piece)
        for index in range(len(parts) - 1):
            left_tokens = _tokens(parts[index])
            left = _left_operand(left_tokens) if index == 0 else _right_operand(left_tokens)
            if index > 0 and left is not None and len(left) != len(left_tokens):
                left = None  # A middle term must be one whole operation.
            right = _right_operand(_tokens(parts[index + 1]))
            if not left or not right:
                continue
            left_expr, right_expr = _expression(left), _expression(right)
            if left_expr is None or right_expr is None or left_expr[1] == 0:
                continue
            computed, stated = _evaluate(left_expr[0]), _evaluate(right_expr[0])
            if computed is None or stated is None:
                continue
            decimals = _decimals(right) if right_expr[1] == 0 else 2
            tolerance = max(
                Decimal(5) * Decimal(10) ** (-decimals - 1) + Decimal("0.0001"),
                abs(computed) * Decimal("0.001"),
            )
            checked.append(key := (left_expr[0], right_expr[0]))
            if abs(computed - stated) <= tolerance:
                continue
            if key in seen:
                continue
            seen.add(key)
            errors.append(
                {
                    "operation": _display(left),
                    "stated": _display(right),
                    "correct": french_amount(computed)
                    + (" €" if any(v == "€" for _, v in right) else ""),
                }
            )
    return errors


def correction_notice(errors: list[dict]) -> str:
    lines = [
        "",
        "",
        "---",
        "**Vérification automatique des calculs** : "
        + (
            "une opération ci-dessus est inexacte."
            if len(errors) == 1
            else "des opérations ci-dessus sont inexactes."
        ),
    ]
    for item in errors:
        lines.append(f"- {item['operation']} = **{item['correct']}** (et non {item['stated']})")
    lines.append("Les montants et conclusions qui en découlent sont à relire avec ce résultat.")
    return "\n".join(lines)
