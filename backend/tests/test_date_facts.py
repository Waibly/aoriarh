import datetime

from app.rag.date_facts import add_months, date_facts_block, elapsed, extract_dates

TODAY = datetime.date(2026, 11, 25)


def test_elapsed_counts_whole_months_then_days():
    assert elapsed(datetime.date(2026, 9, 1), TODAY) == (0, 2, 24)
    assert elapsed(datetime.date(2017, 9, 18), datetime.date(2027, 3, 31)) == (9, 6, 13)
    assert elapsed(datetime.date(2026, 1, 31), datetime.date(2026, 2, 28)) == (0, 1, 0)


def test_add_months_clamps_to_month_end():
    assert add_months(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)
    assert add_months(datetime.date(2026, 11, 30), 3) == datetime.date(2027, 2, 28)


def test_trial_period_question_gets_presence_end_and_friday():
    block = date_facts_block(
        ["Embauche le 1er septembre 2026, essai de 2 mois. Il part vendredi ?"],
        TODAY,
    )
    assert "2 mois et 24 jours" in block
    assert "moins de 3 mois" in block
    assert "s'achève le samedi 31 octobre 2026" in block
    assert "Prochain vendredi : vendredi 27 novembre 2026" in block


def test_month_end_period_ends_with_short_month():
    block = date_facts_block(["contrat du 31/01/2026 pour 1 mois"], TODAY)
    assert "s'achève le samedi 28 février 2026" in block


def test_year_assumed_is_flagged_and_numeric_dates_read():
    dates = extract_dates("entré le 3 mars, sorti le 15/06/26", TODAY)
    assert dates == [(datetime.date(2026, 3, 3), True), (datetime.date(2026, 6, 15), False)]
    assert "année non précisée" in date_facts_block(["entré le 3 mars"], TODAY)


def test_no_block_without_dates_and_article_numbers_ignored():
    assert date_facts_block(["Que dit l'article L1221-25 ? 2.600 € et 35 heures"], TODAY) is None
