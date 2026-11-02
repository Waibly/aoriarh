from types import SimpleNamespace

from app.rag.parent_expansion import (
    MAX_CHARS_PER_DECISION,
    _merge_group,
    reference_source_types,
)
from app.rag.search import SearchResult
from app.rag.search_plan import AnswerIntent, build_deterministic_search_plan
from app.services.conversation_document_service import DocumentLegalSearch
from app.services.conversation_orchestrator import legal_plan


def _chunk(index, text, score=0.0):
    return SearchResult(
        text=text, doc_name="CA", document_id="decision", source_type="arret_cour_appel",
        norme_niveau=4, norme_poids=0.5, chunk_index=index, score=score,
    )


def test_bare_article_number_is_scoped_to_the_named_agreement_family():
    ccn = reference_source_types("Que dit l'article 12 de la convention collective ?")
    assert ccn == {"12": ["convention_collective_nationale", "accord_branche"]}
    company = reference_source_types("Selon l'article 5 de notre accord d'entreprise")
    assert company == {"5": ["accord_entreprise", "accord_performance_collective"]}
    assert reference_source_types("article L1234-9 du code du travail") == {
        "L1234-9": ["code_travail", "code_travail_reglementaire"]
    }


def test_short_decision_is_kept_whole():
    chunks = [_chunk(i, "x" * 1000) for i in range(4)]
    merged = _merge_group(chunks, 0.9, seeds=[_chunk(2, "x" * 1000, 0.9)], complete_document=True)
    assert merged.context_chunk_indices == [0, 1, 2, 3]


def test_long_decision_keeps_header_ranked_passages_neighbours_and_end():
    chunks = [_chunk(i, f"p{i} " + "x" * 2500) for i in range(30)]
    seed = _chunk(12, chunks[12].text, 0.8)
    merged = _merge_group(chunks, 0.8, seeds=[seed], complete_document=True)
    assert merged.context_chunk_indices == [0, 11, 12, 13, 29]
    assert merged.context_available_chunk_count == 30
    assert len(merged.text) <= MAX_CHARS_PER_DECISION + 10


def _search(question):
    return DocumentLegalSearch(
        standalone_question=question, needs_history=False, legal_topics=[],
        search_queries=[question], hypothesized_articles=[], source_hints=[],
        jurisprudence="optional", answer_intent=AnswerIntent.FACTUAL_RULE, missing_facts=[],
    )


def test_each_branch_of_a_multi_search_plan_uses_its_own_question():
    original = "Question A sur la période d'essai, et question B sur le préavis"
    first = SimpleNamespace(action="search_legal", id="a", query="Question A",
                            legal_search=_search("Question A"))
    second = SimpleNamespace(action="search_legal", id="b", query="Question B",
                             legal_search=_search("Question B"))
    planned = SimpleNamespace(
        legal_base=build_deterministic_search_plan(original), requests=[], raw=None,
        plan=SimpleNamespace(actions=[first, second]),
    )
    assert legal_plan(planned, first).query_original == "Question A"
    assert legal_plan(planned, second).query_original == "Question B"
    planned.plan.actions = [first]
    assert legal_plan(planned, first).query_original == original
