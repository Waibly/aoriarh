"""Bounded arithmetic only: no eval, calls, attribute access or generated code."""

import ast
from decimal import Decimal, DecimalException, localcontext

from pydantic import BaseModel, ConfigDict, Field


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
        try:
            # Only an entire decimal literal is accepted; never extract digits from prose.
            actual = Decimal(value) if isinstance(value, str) else None
            proposed = Decimal(variable.value)
            if actual is None or not actual.is_finite() or actual != proposed:
                raise ValueError("calculation_fact_value_mismatch")
        except DecimalException as exc:
            raise ValueError("calculation_fact_requires_numeric_value") from exc
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
            return str(visit(tree.body))
    except DecimalException as exc:
        raise ValueError("calculation_arithmetic_error") from exc
