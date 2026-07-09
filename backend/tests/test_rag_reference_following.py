"""Tests de l'extraction 'articles modifiés par un texte' (reference-following) :
un décret/loi qui MODIFIE un article -> on suit vers l'article consolidé.
Une simple CITATION d'article ne doit jamais déclencher le suivi."""
from app.rag.agent import _extract_modified_articles


def test_article_rewritten():
    assert _extract_modified_articles("L'article D. 241-7 est ainsi rédigé : ...") == {"D241-7"}


def test_article_modified_and_abrogated():
    txt = ("Le code est ainsi modifié : 1° L'article D. 241-1-2 est abrogé ; "
           "4° L'article D. 241-7 est ainsi rédigé ; L'article D. 711-10 est ainsi modifié.")
    assert _extract_modified_articles(txt) == {"D241-1-2", "D241-7", "D711-10"}


def test_insertion_after_article():
    assert "D241-7" in _extract_modified_articles(
        "Après l'article D. 241-7 est inséré un article D. 241-7-1 ainsi rédigé"
    )


def test_law_article_reference():
    assert _extract_modified_articles("L'article L. 241-13 est ainsi modifié") == {"L241-13"}


def test_plain_citation_does_not_trigger():
    # Citation simple, pas de modification -> aucun suivi (évite d'injecter n'importe quoi).
    assert _extract_modified_articles(
        "Selon l'article L. 3141-5 du code du travail, le salarié acquiert 2 jours par mois."
    ) == set()


def test_empty_and_none():
    assert _extract_modified_articles("") == set()
    assert _extract_modified_articles(None) == set()
