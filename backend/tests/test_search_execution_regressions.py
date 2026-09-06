"""Exercise actual Qdrant filters plus controlled branch failures; no network."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.agent import RAGAgent
from app.rag.parent_expansion import fetch_by_identifiers, reference_source_types
from app.rag.qdrant_store import COLLECTION_NAME
from app.rag.search import HybridSearch, SearchResult
from app.rag.search_feedback import search_feedback
from app.rag.search_plan import (
    apply_compact_planner_payload,
    build_deterministic_search_plan,
    run_compact_search_planner,
)


def agent():
    obj = RAGAgent.__new__(RAGAgent)
    obj.search_engine = MagicMock()
    obj.search_engine.search = AsyncMock(return_value=[])
    obj._org_id = "org"
    obj._user_id = obj._conversation_id = None
    obj._is_replay = True
    return obj


def result(doc="code", source_type="code_travail"):
    return SearchResult("Texte témoin", doc, doc, source_type, 3, 0.9, 0, 0.5)


@pytest.fixture
def corpus():
    client = QdrantClient(":memory:")
    client.create_collection(
        COLLECTION_NAME, vectors_config=VectorParams(size=2, distance=Distance.COSINE)
    )
    docs = [
        ("common", "code_travail", None, ["L1235-3-1"]),
        ("common", "code_securite_sociale", None, ["L1235-3-1"]),
        ("other-org", "code_travail", None, ["L1235-3-1"]),
        ("common", "convention_collective_nationale", "1486", ["1"]),
        ("common", "convention_collective_nationale", "0413", ["1"]),
        ("org", "contrat_travail", None, ["1"]),
    ]
    client.upsert(
        COLLECTION_NAME,
        [
            PointStruct(
                id=i,
                vector=[1.0, 0.0],
                payload={
                    "organisation_id": org,
                    "source_type": st,
                    "idcc": idcc,
                    "article_nums": articles,
                    "document_id": str(i),
                    "chunk_index": 0,
                    "text": "Document témoin de filtrage",
                },
            )
            for i, (org, st, idcc, articles) in enumerate(docs)
        ],
    )
    yield client
    client.close()


async def test_exact_lookup_matches_code_and_tenant_in_real_qdrant(corpus):
    found = await fetch_by_identifiers(
        corpus,
        {"article_nums": ["L1235-3-1"]},
        "org",
        reference_query="article L.1235-3-1 du Code du travail",
    )
    assert [r.document_id for r in found] == ["0"]


def test_code_association_is_per_reference():
    scopes = reference_source_types("L.1234-9 du Code du travail et article 1240 du Code civil")
    assert scopes["L1234-9"] == ["code_travail", "code_travail_reglementaire"]
    assert scopes["1240"] == ["code_civil", "code_civil_reglementaire"]


def test_exclusion_and_idcc_filter_in_real_qdrant(corpus):
    search = HybridSearch.__new__(HybridSearch)
    scope = search._build_org_filter("org", ["1486"], excluded_source_types=["contrat_travail"])
    points, _ = corpus.scroll(COLLECTION_NAME, scroll_filter=scope, limit=20)
    assert {p.id for p in points} == {0, 1, 3}
    empty = search._build_org_filter("org", ["1486"], source_type_filter=[])
    assert corpus.scroll(COLLECTION_NAME, scroll_filter=empty)[0] == []


async def test_successful_floor_survives_failed_main_branches():
    obj = agent()

    async def search(query, org, **kwargs):
        if kwargs.get("source_type_filter"):
            return [result()]
        raise RuntimeError("simulated main branch outage")

    obj.search_engine.search.side_effect = search
    found = await obj._run_variant_searches(["question"], "ancre", "org")
    assert [r.document_id for r in found] == ["code"]
    assert {b["status"] for b in obj._branch_diagnostics} == {"ok", "error"}


async def test_exact_reference_keeps_ccn_and_reuses_identifier_lookup():
    obj = agent()
    plan = build_deterministic_search_plan(
        "Selon la CCN, comment appliquer L.1234-9 ?",
        org_idcc_list=["1486"],
    )
    with patch(
        "app.rag.agent.fetch_by_identifiers", new=AsyncMock(return_value=[result()])
    ) as fetch:
        found, _ = await obj._search_with_plan(plan, plan.query_original, "org", ["1486"])
        await obj._inject_identifier_matches(plan.query_original, found, "org", ["1486"])
    assert fetch.await_count == 1
    assert any(
        "convention_collective_nationale" in (c.kwargs.get("source_type_filter") or [])
        for c in obj.search_engine.search.await_args_list
    )


async def test_boss_hint_gets_its_own_branch():
    obj = agent()
    plan = replace(
        build_deterministic_search_plan("Quels frais professionnels exonérer ?"),
        planner_source_hints=["boss"],
    )
    await obj._search_with_plan(plan, plan.query_original, "org")
    assert any(
        c.kwargs.get("source_type_filter") == ["boss"]
        for c in obj.search_engine.search.await_args_list
    )


@pytest.mark.parametrize(
    "query",
    [
        "Ne cherche pas dans la CCN, quel préavis ?",
        "Uniquement dans le Code du travail, quel préavis ?",
    ],
)
async def test_source_constraints_cover_auxiliary_branches(query):
    obj = agent()
    plan = replace(
        build_deterministic_search_plan(query, org_idcc_list=["1486"]),
        planner_source_hints=["ccn", "boss", "internal"],
    )
    await obj._search_with_plan(plan, query, "org", ["1486"])
    for call in obj.search_engine.search.await_args_list:
        types = call.kwargs.get("source_type_filter") or []
        assert "convention_collective_nationale" not in types
        if plan.exclusive_source_types:
            assert set(types) <= set(plan.exclusive_source_types)
        else:
            assert "convention_collective_nationale" in call.kwargs["excluded_source_types"]


async def test_invalid_nonempty_planner_output_is_preserved_with_usage():
    raw = '  {"standalone_question": "incomplet"\n'
    llm = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))],
                        usage=SimpleNamespace(prompt_tokens=101, completion_tokens=11),
                    ),
                )
            )
        )
    )
    output = await run_compact_search_planner(
        build_deterministic_search_plan("Quel préavis ?"),
        llm=llm,
        model="test",
    )
    assert output.plan.planner_raw_response == raw
    assert (output.prompt_tokens, output.completion_tokens) == (101, 11)
    details = search_feedback({"search_plan": output.plan.to_dict()})
    assert details["raw_response"] == raw
    assert details["warnings"]
    assert llm.chat.completions.create.await_count == 1


def test_long_question_and_contextualized_followup_preserve_raw_fields():
    question = "Question autonome détaillée. " * 50
    plan = build_deterministic_search_plan(question)
    payload = {
        "standalone_question": question,
        "search_queries": ["préavis"],
        "source_hints": [],
        "hypothesized_articles": [],
    }
    assert apply_compact_planner_payload(plan, payload).standalone_question == question
    followup = build_deterministic_search_plan("Et les cadres ?", has_history=True)
    payload["standalone_question"] = "Quel préavis pour les cadres selon la convention collective ?"
    enriched = apply_compact_planner_payload(followup, payload)
    assert enriched.query_original == "Et les cadres ?"
    assert enriched.requested_source_types == followup.requested_source_types


async def test_encodings_shared_only_within_one_request():
    engine = HybridSearch.__new__(HybridSearch)
    engine.qdrant = MagicMock()
    engine.qdrant.query_points.return_value = SimpleNamespace(points=[])
    engine._encode_dense = AsyncMock(return_value=[1.0, 0.0])
    engine._encode_sparse_sync = MagicMock(return_value={"indices": [1], "values": [1.0]})
    cache = {}
    await asyncio.gather(
        engine.search("question", "org", encoding_cache=cache),
        engine.search("question", "org", source_type_filter=["boss"], encoding_cache=cache),
    )
    assert engine._encode_dense.await_count == 1
    assert engine.qdrant.query_points.call_count == 2
    await engine.search("question", "other-org", encoding_cache={})
    assert engine._encode_dense.await_count == 2


async def test_article_in_model_topics_cannot_bypass_hypothesis_lookup():
    obj = agent()
    plan = replace(
        build_deterministic_search_plan("Quel préavis ?"), legal_topics=["préavis L9999-1"]
    )
    with patch("app.rag.agent.fetch_by_identifiers", new=AsyncMock()) as fetch:
        await obj._search_with_plan(plan, plan.query_original, "org")
    fetch.assert_not_awaited()


async def test_classifier_invalid_raw_output_remains_available():
    from app.rag.intent_router import classify_intent

    raw = "  résultat hors JSON\n"
    llm = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))],
                    )
                ),
            )
        )
    )
    output = await classify_intent("Quel préavis ?", None, llm)
    assert output.raw_response == raw
    assert output.intent.value == "routing_error"
    assert output.static_answer is not None
    assert llm.chat.completions.create.await_count == 1


def test_historical_application_does_not_filter_publication_dates():
    from app.rag.agent import _plan_time_bounds

    plan = build_deterministic_search_plan("Quelles règles applicables en 2024 ?")
    assert plan.time_scope["kind"] == "application_year"
    assert _plan_time_bounds(plan) == (None, None)


def test_feedback_does_not_depend_on_full_trace_serialization():
    trace = SimpleNamespace(
        search_plan={"planner_raw_response": "  brut\n"},
        search_plan_validation={},
        router_raw_response=None,
        to_dict=MagicMock(side_effect=RuntimeError("broken trace")),
    )
    assert search_feedback(trace)["raw_response"] == "  brut\n"
    trace.to_dict.assert_not_called()


def test_only_a_population_is_not_an_exclusive_source_request():
    plan = build_deterministic_search_plan("Seulement pour les cadres, selon la CCN quel préavis ?")
    assert plan.exclusive_source_types == []


def test_recent_facts_do_not_become_a_publication_filter():
    assert (
        build_deterministic_search_plan(
            "Un salarié absent les 30 derniers jours : quelle procédure ?"
        ).time_scope
        is None
    )


def test_model_can_flag_a_missed_anaphora_without_rewriting_autonomous_questions():
    plan = build_deterministic_search_plan("Pour eux aussi ?", has_history=True)
    payload = {"standalone_question": "Quel préavis pour les cadres ?", "needs_history": True}
    assert apply_compact_planner_payload(plan, payload).needs_condensation
    autonomous = build_deterministic_search_plan(
        "Nouvelle question : comment organiser les élections du CSE ?",
        has_history=True,
    )
    payload["needs_history"] = False
    enriched = apply_compact_planner_payload(autonomous, payload)
    assert not enriched.needs_condensation
    assert enriched.query_original == autonomous.query_original


async def test_timeout_of_main_search_keeps_successful_floor(monkeypatch):
    monkeypatch.setattr("app.rag.agent.RAG_TIMEOUT_PER_STEP", 0.01)
    obj = agent()

    async def search(query, org, **kwargs):
        if kwargs.get("source_type_filter"):
            return [result()]
        await asyncio.Event().wait()

    obj.search_engine.search.side_effect = search
    assert await obj._run_variant_searches(["question"], "ancre", "org")
    assert {b["status"] for b in obj._branch_diagnostics} == {"ok", "error"}


async def test_historical_article_spelling_is_still_retrievable(corpus):
    corpus.upsert(COLLECTION_NAME, [PointStruct(id=20, vector=[1., 0.], payload={
        "organisation_id": "common", "source_type": "code_securite_sociale",
        "article_nums": ["L. 242-1-4"], "document_id": "historical", "chunk_index": 0,
    })])
    found = await fetch_by_identifiers(corpus, {"article_nums": ["L242-1-4"]}, "org")
    assert [r.document_id for r in found] == ["historical"]


def test_ccn_decimal_article_is_not_truncated_to_its_parent():
    from app.rag.parent_expansion import detect_identifiers

    assert detect_identifiers("article 9.1 de la convention collective")["article_nums"] == ["9.1"]


async def test_boss_is_not_forced_without_a_model_hint():
    obj = agent()
    plan = build_deterministic_search_plan("Quels frais professionnels exonérer ?")
    assert plan.planner_source_hints == []
    await obj._search_with_plan(plan, plan.query_original, "org")
    assert not any(call.kwargs.get("source_type_filter") == ["boss"]
               for call in obj.search_engine.search.await_args_list)


async def test_unchanged_planner_keeps_raw_output_without_reconstructing_context():
    obj = agent()
    query = "Et les cadres ?"
    anchor = "Quelle durée de préavis pour une démission ?"
    raw = '{"standalone_question":"Et les cadres ?"}'
    llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw))], usage=None,
        )),
    )))
    planned = await run_compact_search_planner(
        build_deterministic_search_plan(query, has_history=True), llm=llm, model="test",
        history=[{"role": "user", "content": anchor}],
    )
    assert planned.plan.planner_raw_response == raw
    assert planned.plan.standalone_question == query
    _, variants = await obj._search_with_plan(planned.plan, query, "org")
    assert anchor + "\n" + query not in variants


async def test_generated_queries_are_executed_without_cleanup_or_truncation():
    obj = agent()
    queries = ["  préavis\n cadres  ", "  préavis\n cadres  ", "x" * 500]
    payload = {
        "standalone_question": "  Quel préavis ?\n",
        "search_queries": queries,
        "legal_topics": ["  sujet\n brut  "],
    }
    plan = apply_compact_planner_payload(
        build_deterministic_search_plan("Quel préavis ?"), payload,
    )
    assert plan.search_queries == queries
    assert plan.legal_topics == payload["legal_topics"]
    _, variants = await obj._search_with_plan(plan, plan.query_original, "org")
    assert variants == [payload["standalone_question"], *queries]


def test_identical_generated_question_does_not_trigger_semantic_warning():
    plan = build_deterministic_search_plan("Et les cadres ?", has_history=True)
    enriched = apply_compact_planner_payload(
        plan, {"standalone_question": plan.query_original},
    )
    assert "planner_condensation_unchanged" not in enriched.warnings
    assert search_feedback({"search_plan": enriched.to_dict()})["warnings"] == []


def test_planner_history_keeps_selected_messages_verbatim():
    import json

    from app.rag.search_plan import _planner_user_message

    content = "  réponse précédente\n" * 150
    history = [{"role": "assistant", "content": content}]
    message = _planner_user_message(
        build_deterministic_search_plan("Suite ?", has_history=True),
        history=history, org_context=None,
    )
    assert json.loads(message)["conversation_history"] == history


async def test_auxiliary_search_does_not_construct_query_from_topics():
    obj = agent()
    obj._run_variant_searches = AsyncMock(return_value=[])
    plan = apply_compact_planner_payload(
        build_deterministic_search_plan("Quel préavis ?"),
        {"standalone_question": "  question brute\n", "legal_topics": ["A", "B"]},
    )
    await obj._search_with_plan(plan, plan.query_original, "org")
    assert obj._run_variant_searches.await_args.args[1] == "  question brute\n"


async def test_explicit_empty_source_scope_is_never_broadened():
    obj = agent()
    obj._active_search_plan = replace(
        build_deterministic_search_plan("question"), exclusive_source_types=["boss"],
    )
    assert await obj._search("question", "org", source_type_filter=[]) == []
    obj.search_engine.search.assert_not_awaited()


async def test_total_retrieval_failure_is_not_reported_as_no_documents():
    obj = agent()
    obj.search_engine.search.side_effect = RuntimeError("unavailable")
    obj.reranker = MagicMock()
    obj.reranker.rerank = AsyncMock()
    plan = build_deterministic_search_plan("question")
    results, _, trace = await obj.prepare_context("question", "org", search_plan=plan)
    assert results == []
    assert trace.error == "search_retrieval_error"
    assert all(b["status"] == "error" for b in trace.search_plan_validation["branches"])
    obj.reranker.rerank.assert_not_awaited()


@pytest.mark.parametrize("raw", [None, "", "  sortie non JSON\n"])
async def test_default_entry_point_never_uses_legacy_search_on_planner_failure(raw):
    obj = agent()
    create = AsyncMock(return_value=SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))], usage=None,
    ))
    obj.llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    obj._search_with_plan = AsyncMock()
    results, _, trace = await obj.prepare_context(
        "Et les cadres ?", "org", history=[{"role": "user", "content": "Question précédente"}],
    )
    assert results == []
    assert trace.error == "search_planner_error"
    assert trace.search_plan["planner_raw_response"] == (raw or None)
    create.assert_awaited_once()
    obj._search_with_plan.assert_not_awaited()
    obj.search_engine.search.assert_not_awaited()


async def test_default_entry_point_reports_transport_error_without_retry():
    obj = agent()
    create = AsyncMock(side_effect=RuntimeError("transport failed"))
    obj.llm = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    results, _, trace = await obj.prepare_context("Question", "org")
    assert results == []
    assert trace.error == "search_planner_error"
    create.assert_awaited_once()
    obj.search_engine.search.assert_not_awaited()


def test_legacy_search_entry_points_are_removed():
    for name in (
        "_condense_question", "_running_topic", "_expand_queries", "_generate_legal_anchor",
        "_parse_variants", "_search_with_expansion", "_build_expand_user_message",
    ):
        assert not hasattr(RAGAgent, name)
