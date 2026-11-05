"""Operations written by the answer model are recomputed; only certain readings count."""

import pytest

from app.rag.answer_arithmetic import correction_notice, find_arithmetic_errors


@pytest.mark.parametrize(
    "answer,operation,correct",
    [
        # Seen on the replay bench (Syntec severance): wrong statutory amount, wrong conclusion.
        (
            "| Indemnité légale | 2 850 € × 1/4 × 9,5 = **7 125 €** |",
            "2 850 € × 1/4 × 9,5",
            "6 768,75 €",
        ),
        # Right formula, wrong result (rupture conventionnelle).
        (
            "Calcul légal : **2 800 € × 1/4 × 82/12 = 3 983,33 €**.",
            "2 800 € × 1/4 × 82/12",
            "4 783,33 €",
        ),
        ("Soit 24 h × 52 / 12 = 140 heures.", "24 h × 52/12", "104"),
    ],
)
def test_wrong_results_are_reported(answer, operation, correct):
    [error] = find_arithmetic_errors(answer)
    assert error["operation"] == operation
    assert error["correct"] == correct


@pytest.mark.parametrize(
    "answer",
    [
        "2 850 € × 1/3 × 9,5 = **9 025 €**",
        "2 600 + (3 000 / 12) = **2 850 €**",
        "1 450 € / 104 h = **13,94 € brut par heure**",
        # Rounded intermediate step.
        "2 850 € × (1/3 × 9,5) = 2 850 € × 3,1667 = **9 025 €**",
        "30 000 € × 15 % = 4 500 €",
        "5 × 1/4 × 2 500 = 3 125",
    ],
)
def test_right_results_are_not_reported(answer):
    checked = []
    assert find_arithmetic_errors(answer, checked) == []
    assert checked  # Read, not skipped.


@pytest.mark.parametrize(
    "answer",
    [
        # Not arithmetic, or not readable with certainty: never corrected.
        "seuil légal de mise en place = 11 salariés",
        "“majorité” = 50 % + 1 voix (pas 50/50)",
        "Période 1 : janvier à mai = 5/12",
        "du 18 septembre 2017 au 31 mars 2027 = 9 ans et 6 mois",
        "82 / 12 = 6 ans et 10 mois",
        # The first factor is in words ("le tiers de").
        "le tiers de 3 × 2 900 € = 2 900 €",
        "2 500 € brut par mois × 3 × 2 = 15 000 €",
        "T0 + 12 mois = 1ère campagne",
        r"\[ 2\,850 \times 3 = 9\,000 \]",
    ],
)
def test_uncertain_readings_are_ignored(answer):
    assert find_arithmetic_errors(answer) == []


def test_notice_gives_the_correct_result():
    notice = correction_notice(find_arithmetic_errors("2 850 € × 1/4 × 9,5 = 7 125 €"))
    assert "2 850 € × 1/4 × 9,5 = **6 768,75 €** (et non 7 125 €)" in notice
    assert notice.startswith("\n\n---\n**Vérification automatique des calculs**")
