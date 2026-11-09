"""Technical contracts for explicit references to dated legal texts."""

import datetime

import pytest

from app.rag.instrument_references import (
    InstrumentReference,
    amended_code_articles,
    detect_instrument_references,
    sql_like_patterns,
    title_matches,
)


def refs(text):
    return [(r.kind, r.number, r.date) for r in detect_instrument_references(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "quelles sanctions depuis la loi du 25 juin 2026 ?",
            [("loi", None, datetime.date(2026, 6, 25))],
        ),
        (
            "La loi n° 2026-534 du 25 juin 2026 change-t-elle le DUERP ?",
            [("loi", "2026-534", datetime.date(2026, 6, 25))],
        ),
        ("loi 2026-534", [("loi", "2026-534", None)]),
        ("décret n°2022-395 du 18 mars 2022", [("decret", "2022-395", datetime.date(2022, 3, 18))]),
        ("Ordonnance n ° 2017-1385", [("ordonnance", "2017-1385", None)]),
        ("arrêté du 1er juillet 2025", [("arrete", None, datetime.date(2025, 7, 1))]),
        ("Décret du 31 fevrier 2025", []),
        ("la loi du 25 juin", []),
        ("la loi Travail", []),
        ("le DUERP depuis 2026", []),
    ],
)
def test_detects_only_complete_references(text, expected):
    assert refs(text) == expected


def test_same_reference_in_original_and_standalone_question_is_kept_once():
    found = detect_instrument_references("loi du 25 juin 2026", "la loi du 25 juin 2026 ?")
    assert len(found) == 1


LAW = InstrumentReference("loi", None, datetime.date(2026, 6, 25), "loi du 25 juin 2026")


def test_title_must_open_with_the_referenced_text():
    assert title_matches(
        LAW,
        "LOI n° 2026-534 du 25 juin 2026 relative à la lutte contre les fraudes sociales",
    )
    assert not title_matches(
        LAW,
        "Décret n° 2026-900 du 2 octobre 2026 portant application de la loi n° 2026-534 "
        "du 25 juin 2026",
    )
    assert not title_matches(LAW, "LOI n° 2026-600 du 26 juin 2026 relative à autre chose")
    number = InstrumentReference("ordonnance", "2019-784", None, "")
    assert title_matches(number, "Ordonnance n ° 2019-784 du 24 juillet 2019 modifiant le code")
    assert not title_matches(number, "Ordonnance n° 2019-7840 du 24 juillet 2019")
    first = InstrumentReference("arrete", None, datetime.date(2025, 7, 1), "")
    assert title_matches(first, "Arrêté du 1er juillet 2025 modifiant l'arrêté du 6 mai 2025")
    assert sql_like_patterns(first)[0] == "% du 1er juillet 2025%"


AMENDING_ARTICLE = (
    "### Article 48\n\nI. - Le code de la sécurité sociale est ainsi modifié :\n\n"
    "1° L'article L. 114-10 est ainsi modifié : ...\n\n"
    "II. - Le code du travail est ainsi modifié :\n\n"
    "1° L'article L. 8113-5 est ainsi modifié :\n"
    "« Les constatations ... prévues au présent chapitre ou au code de la sécurité "
    "sociale. » ;\n\n"
    "2° L'article L. 8115-1 est complété par un 6° ainsi rédigé :\n\n"
)
INSERTED = (
    "### Article 48 (suite)\n\n« 6° Aux dispositions des I et II de l'article L. 4121-3-1 "
    "relatives au document unique d'évaluation des risques professionnels, en cas "
    "d'absence du document. »"
)


def test_amended_article_is_the_last_one_announced_before_the_passage():
    articles = amended_code_articles(AMENDING_ARTICLE + INSERTED, len(AMENDING_ARTICLE))
    assert articles == [
        {
            "article": "L8115-1",
            "source_types": ["code_travail", "code_travail_reglementaire"],
            "role": "amended",
        },
        {
            "article": "L4121-3-1",
            "source_types": ["code_travail", "code_travail_reglementaire"],
            "role": "cited",
        },
    ]


def test_code_named_inside_inserted_wording_does_not_scope_the_amended_article():
    text = (
        "Le code du travail est ainsi modifié :\n"
        "« ... au code de la sécurité sociale. » ;\n"
        "2° L'article L. 8115-1 est complété :\n\n"
    )
    assert amended_code_articles(text + "« 6° ... »", len(text))[0]["source_types"][0] == (
        "code_travail"
    )


def test_article_without_a_named_code_is_not_followed():
    text = "1° L'article L. 8115-1 est complété :\n\n"
    assert amended_code_articles(text + "« 6° ... »", len(text)) == []


def test_explicit_code_after_the_article_wins():
    text = "Après l'article L. 4121-3 du code du travail, il est inséré :\n\n"
    assert amended_code_articles(text + "« ... »", len(text)) == [
        {
            "article": "L4121-3",
            "source_types": ["code_travail", "code_travail_reglementaire"],
            "role": "amended",
        }
    ]


def passage(doc, index, score=0.5, articles=None, section="S"):
    from app.rag.search import SearchResult

    return SearchResult(
        f"texte {doc} {index}",
        doc,
        doc,
        "code_travail",
        3,
        0.9,
        index,
        score,
        article_nums=articles,
        section_path=section,
    )


def test_linked_articles_follow_only_a_selected_cited_passage():
    from app.rag.agent import RAGAgent

    law = passage("loi", 86, 0.63, ["48"])
    links = {
        ("loi", 86): [
            passage("code", 3129, 0, ["L8115-1"]),
            passage("code", 3130, 0, ["L8115-1"]),
            passage("code", 3131, 0, ["L8115-2", "L8115-3"]),
        ],
        ("loi", 118): [passage("code", 9000, 0, ["L6231-2"])],
    }
    diagnostics = []
    out = RAGAgent._append_instrument_links([law], links, diagnostics)
    assert out[0] is law
    added = out[1:]
    assert [r.context_chunk_indices for r in added] == [[3129, 3130], [3131]]
    assert added[0].text == "texte code 3129\n\ntexte code 3130"
    assert all(r.score == 0.0 for r in added)
    assert diagnostics[0]["added_groups"] == 2


def test_linked_articles_are_bounded_and_never_duplicated():
    from app.rag.agent import _INSTRUMENT_LINKED_GROUPS, RAGAgent

    law = passage("loi", 1, 0.9, ["1"])
    already = passage("code", 0, 0.8, ["L1"])
    links = {("loi", 1): [passage("code", i, 0, [f"L{i}"]) for i in range(10)]}
    out = RAGAgent._append_instrument_links([law, already], links, [])
    added = out[2:]
    assert len(added) == _INSTRUMENT_LINKED_GROUPS
    assert 0 not in {i for r in added for i in r.context_chunk_indices}


def test_no_cited_text_leaves_selection_unchanged():
    from app.rag.agent import RAGAgent

    selected = [passage("x", 1)]
    assert RAGAgent._append_instrument_links(selected, {}, []) == selected
