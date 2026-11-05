from decimal import Decimal

import pytest

from app.services.case_calculation import (
    CalculationSpec,
    CalculationVariable,
    calculate,
    parse_decimal_text,
    units_compatible,
    validate_fact_bindings,
)


@pytest.mark.parametrize(
    "value,status,error",
    [
        ("9999", "active", "value_mismatch"),
        ("3200.10", "contested", "not_active"),
        ("environ 3 200,10 € par mois selon le bulletin", "active", "requires_numeric_value"),
        ("3.200", "active", "requires_numeric_value"),
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


@pytest.mark.parametrize(
    "fact_unit,variable_unit,compatible",
    [
        ("euros", "€ brut par mois", True),  # Seen in production (Syntec severance).
        ("EUR brut/mois", "euros brut par mois", True),
        ("euros par an", "€ par mois", False),
        ("€/an", "EUR brut mensuel", False),
        ("EUR", "USD", False),
        ("heures", "jours", False),
        ("mois", "mois", True),
    ],
)
def test_amount_units_are_reconciled_but_not_across_currency_or_period(
    fact_unit, variable_unit, compatible
):
    assert units_compatible(fact_unit, variable_unit) is compatible


def test_decimal_arithmetic():
    assert calculate(specification("salary * 3 + 0.1")) == "9600.40"


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("salary × 3", "9600.30"),  # Seen in production: the planner writes like a person.
        ("salary ÷ 2", "1600.05"),
        ("salary − 0,10", "3200.00"),
        ("salary · 1,5", "4800.150"),
    ],
)
def test_typographic_operators_are_accepted(expression, expected):
    assert calculate(specification(expression)) == expected


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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3200.10", "3200.10"),
        ("3 200,10 €", "3200.10"),
        ("3\u202f200,10 euros", "3200.10"),
        ("2600", "2600"),
        ("35 heures", "35"),
        ("-12,5 %", "-12.5"),
        ("1E+3", "1000"),
        ("3.200", None),
        ("environ 2 600 €", None),
        ("2 600 € puis 2 800 €", None),
        ("", None),
    ],
)
def test_user_typed_numbers_are_read_whole_or_not_at_all(text, expected):
    assert parse_decimal_text(text) == (Decimal(expected) if expected is not None else None)


def test_user_typed_fact_is_bound_to_the_calculation():
    entry = {"id": "fact", "key": "salary", "value_text": "3 200,10 €", "status": "confirmed"}
    assert validate_fact_bindings(specification("salary * 3"), [entry]) == ["fact"]


def test_results_use_plain_notation_and_bounded_decimals():
    assert calculate(specification("3000 / 3")) == "1000"
    assert calculate(specification("1 / 3")) == "0.3333333333"
