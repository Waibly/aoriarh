"""Bounded arithmetic only: no eval, calls, attribute access or generated code."""

import ast
import re
from decimal import Decimal, DecimalException, InvalidOperation, localcontext

from pydantic import BaseModel, ConfigDict, Field

# A whole value as users type it: "2600", "2 600", "2 600,50", "2600.5 €", "35 heures".
# Only one number followed by an optional short unit is accepted: digits are never picked
# out of a sentence. "2.600" is ambiguous (French thousands or decimal) and is refused.
_GROUPED = r"\d{1,3}(?:[   ]\d{3})+"
_NUMBER_TEXT = re.compile(
    rf"^\s*(?P<sign>[+-]?)\s*(?P<int>{_GROUPED}|\d+)(?:(?P<sep>[.,])(?P<frac>\d+))?"
    r"\s*(?P<unit>[€%]|[A-Za-zÀ-ÿ€%/.' ]{1,25})?\s*$"
)


def parse_decimal_text(text: str | None) -> Decimal | None:
    """Return the decimal written as the whole text (French or plain notation), else None."""
    if not isinstance(text, str):
        return None
    if re.fullmatch(r"\s*[+-]?(\d+(\.\d*)?|\.\d+)(E[+-]?\d+)?\s*", text, re.IGNORECASE):
        # Plain decimal literal, including results previously stored as "1E+3".
        if not re.fullmatch(r"\s*[+-]?\d{1,3}\.\d{3}\s*", text):
            value = Decimal(text.strip())
            return value if value.is_finite() else None
    match = _NUMBER_TEXT.match(text)
    if match is None:
        return None
    unit = (match["unit"] or "").strip()
    if unit and not re.search(r"[A-Za-zÀ-ÿ€%]", unit):
        return None
    integer = re.sub(r"[   ]", "", match["int"])
    fraction = match["frac"]
    if match["sep"] == "." and len(fraction) == 3 and integer == match["int"] and len(integer) <= 3:
        return None  # "2.600": thousands separator or decimal point, cannot tell.
    try:
        value = Decimal(f"{match['sign']}{integer}{'.' + fraction if fraction else ''}")
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


class CalculationVariable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    value: str = Field(max_length=80)
    unit: str = Field(max_length=100)
    entry_key: str | None
    entry_id: str | None = None


class CalculationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expression: str = Field(min_length=1, max_length=500)
    variables: list[CalculationVariable] = Field(max_length=30)
    source_document_ids: list[str] = Field(max_length=10)
    formula_source: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(max_length=20)
    scenario: str = Field(min_length=1, max_length=500)
    unit: str = Field(max_length=100)


def validate_fact_bindings(spec: CalculationSpec, entries: list[dict]) -> list[str]:
    """Check exact typed inputs, never infer a number from prose or repair a proposal."""
    bound = []
    for variable in spec.variables:
        if variable.entry_key is None and variable.entry_id is None:
            continue  # Explicit scenario constant, retained verbatim in the specification.
        matches = [
            entry
            for entry in entries
            if (variable.entry_key is None or entry.get("key") == variable.entry_key)
            and (variable.entry_id is None or entry["id"] == variable.entry_id)
        ]
        if len(matches) != 1:
            raise ValueError("calculation_fact_missing_or_ambiguous")
        entry = matches[0]
        if entry["status"] not in {"active", "confirmed"}:
            raise ValueError("calculation_fact_not_active")
        structured = entry.get("value_json")
        if isinstance(structured, dict) and "number" in structured:
            value = structured["number"]
            if structured.get("unit") != variable.unit:
                raise ValueError("calculation_fact_unit_mismatch")
        else:
            value = entry.get("value_text")
        # Only a whole numeric value is accepted; never extract digits from prose.
        actual = parse_decimal_text(value)
        if actual is None:
            raise ValueError("calculation_fact_requires_numeric_value")
        try:
            proposed = Decimal(variable.value)
        except DecimalException as exc:
            raise ValueError("calculation_fact_requires_numeric_value") from exc
        if actual != proposed:
            raise ValueError("calculation_fact_value_mismatch")
        bound.append(entry["id"])
    return bound


def calculate(spec: CalculationSpec) -> str:
    """Return exact decimal arithmetic (28 significant digits), or a technical error."""
    values = {item.name: Decimal(item.value) for item in spec.variables}
    if len(values) != len(spec.variables):
        raise ValueError("duplicate_calculation_variable")
    if any(not value.is_finite() or abs(value) > Decimal("1e30") for value in values.values()):
        raise ValueError("calculation_value_out_of_bounds")
    tree = ast.parse(spec.expression, mode="eval")
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("calculation_expression_too_complex")

    def visit(node):
        if isinstance(node, ast.Name) and node.id in values:
            result = values[node.id]
        elif isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            result = Decimal(ast.get_source_segment(spec.expression, node))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            else:
                result = left / right
        else:
            raise ValueError("unsupported_calculation_expression")
        if not result.is_finite() or abs(result) > Decimal("1e30"):
            raise ValueError("calculation_result_out_of_bounds")
        return result

    try:
        with localcontext() as context:
            context.prec = 28
            result = visit(tree.body)
    except DecimalException as exc:
        raise ValueError("calculation_arithmetic_error") from exc
    return format_calculation_result(result)


def format_calculation_result(value: Decimal) -> str:
    """Plain notation (never "1E+3"); non-terminating quotients are kept to 10 decimals."""
    if value.as_tuple().exponent < -10:
        value = value.quantize(Decimal("1e-10")).normalize()
    return format(value, "f")
