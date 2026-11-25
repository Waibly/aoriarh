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


def test_deadlines_from_a_past_fact_are_dated_and_marked_passed():
    block = date_facts_block(["faute découverte le 10 septembre 2026"], TODAY)
    assert "DÉJÀ EXPIRÉS aujourd'hui : 8 jours" in block
    assert "2 mois (le mardi 10 novembre 2026)." in block
    rc = date_facts_block(["rupture conventionnelle signée le 20 novembre 2026"], TODAY)
    assert "15 jours (le samedi 5 décembre 2026)" in rc.split("PAS ENCORE")[1]


def test_expired_reminder_lists_deadlines_already_run_out():
    from app.rag.date_facts import expired_reminder

    line = expired_reminder(["faute découverte le 10 septembre 2026"], TODAY)
    assert "2 mois et 15 jours" in line and "déjà écoulés" in line
    assert expired_reminder(["signée le 30 novembre 2026"], TODAY) is None


def test_working_days_skip_sundays_and_public_holidays():
    from app.rag.date_facts import public_holidays, working_days_after

    assert datetime.date(2026, 4, 6) in public_holidays(2026)  # lundi de Pâques
    assert datetime.date(2026, 5, 14) in public_holidays(2026)  # Ascension
    assert working_days_after(datetime.date(2026, 11, 23), 6)[-2:] == [
        datetime.date(2026, 11, 28),
        datetime.date(2026, 11, 30),
    ]
    assert working_days_after(datetime.date(2026, 11, 7), 3) == [
        datetime.date(2026, 11, 9),
        datetime.date(2026, 11, 10),
        datetime.date(2026, 11, 12),
    ]
