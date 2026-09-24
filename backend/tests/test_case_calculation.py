import pytest

from app.services.case_calculation import (
    CalculationSpec,
    CalculationVariable,
    calculate,
    validate_fact_bindings,
)


@pytest.mark.parametrize(
    "value,status,error",
    [
        ("9999", "active", "value_mismatch"),
        ("3200.10", "contested", "not_active"),
        ("3 200,10 €", "active", "requires_numeric_value"),
    ],
)
def test_calculation_rejects_unbound_or_contested_fact(value, status, error):
    with pytest.raises(ValueError, match=error):
        validate_fact_bindings(
            specification("salary * 3"),
            [
                {"id": "fact", "key": "salary", "value_text": value, "status": status},
            ],
        )


def test_calculation_uses_exact_structured_fact_and_unit():
    entry = {
        "id": "fact",
        "key": "salary",
        "value_text": "3 200,10 €",
        "value_json": {"number": "3200.10", "unit": "EUR"},
        "status": "confirmed",
    }
    spec = specification("salary * 3")
    assert validate_fact_bindings(spec, [entry]) == ["fact"]
    with pytest.raises(ValueError, match="ambiguous"):
        validate_fact_bindings(spec, [entry, {**entry, "id": "other"}])
    entry["value_json"]["unit"] = "USD"
    with pytest.raises(ValueError, match="unit_mismatch"):
        validate_fact_bindings(spec, [entry])


def specification(expression):
    return CalculationSpec(
        expression=expression,
        variables=[
            CalculationVariable(name="salary", value="3200.10", unit="EUR", entry_key="salary")
        ],
        source_document_ids=[],
        formula_source="Formule fournie par l'utilisateur",
        assumptions=["Simulation arithmétique"],
        scenario="Trois mois",
        unit="EUR",
    )


def test_decimal_arithmetic():
    assert calculate(specification("salary * 3 + 0.1")) == "9600.40"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('pwd')",
        "salary.__class__",
        "[salary][0]",
        "salary ** 1000000",
        "salary / 0",
        "unknown + 1",
        "1e1000",
        "True",
    ],
)
def test_unexecutable_arithmetic_is_rejected(expression):
    with pytest.raises((ValueError, ArithmeticError)):
        calculate(specification(expression))
