"""Technical failures must not become empty or partial successful searches."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.rag.agent import RAGAgent
from app.rag.parent_expansion import RetrievalError, fetch_by_identifiers
from app.rag.search import SearchResult
from app.rag.search_feedback import search_feedback
from app.rag.search_plan import build_deterministic_search_plan


async def test_one_failed_branch_is_reported_without_replacement():
    agent = RAGAgent.__new__(RAGAgent)
    agent._org_id = agent._user_id = agent._conversation_id = None
    agent._is_replay = True
    agent._search = AsyncMock(side_effect=[
        [SearchResult("text", "doc", "doc", "code_travail", 1, 1., 0, .5)],
        RuntimeError("offline"),
    ])
    with pytest.raises(RetrievalError, match="search_branch_failed"):
        await agent._run_variant_searches(
            ["first", "second"], "", "org", apply_legislation_floor=False,
        )
    assert agent._search.await_count == 2


async def test_identifier_transport_failure_is_not_no_match():
    qdrant = MagicMock()
    qdrant.scroll.side_effect = RuntimeError("offline")
    diagnostics = []
    with pytest.raises(RetrievalError, match="identifier_lookup_failed"):
        await fetch_by_identifiers(qdrant, {"article_nums": ["L1234-1"]},
                                   organisation_id="org", diagnostics=diagnostics)
    assert diagnostics[0]["status"] == "error"
    qdrant.scroll.assert_called_once()


async def test_identifier_no_match_remains_a_successful_empty_search():
    qdrant = MagicMock()
    qdrant.scroll.return_value = ([], None)
    diagnostics = []
    results = await fetch_by_identifiers(
        qdrant, {"article_nums": ["L1234-1"]},
        organisation_id="org", diagnostics=diagnostics,
    )
    assert results == []
    assert diagnostics and all(branch["status"] == "empty" for branch in diagnostics)


@pytest.mark.parametrize("failure", [RuntimeError("offline"), TimeoutError()])
async def test_complement_errors_are_propagated(failure):
    agent = RAGAgent.__new__(RAGAgent)
    call = AsyncMock(side_effect=failure)
    with pytest.raises(RetrievalError):
        await agent._step_with_timeout(call())
    call.assert_awaited_once()


async def test_cancellation_is_not_converted_to_failure():
    call = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await RAGAgent.__new__(RAGAgent)._step_with_timeout(call())


@pytest.mark.parametrize("stage", ["hybrid", "references"])
async def test_preparation_keeps_raw_plan_and_stops_before_rerank(stage):
    from dataclasses import replace
    plan = replace(build_deterministic_search_plan("L1234-1"),
                   planner_raw_response="  raw plan\n")
    agent = RAGAgent.__new__(RAGAgent)
    agent.search_engine = SimpleNamespace(qdrant=None)
    agent.reranker = SimpleNamespace(rerank=AsyncMock())
    agent._search_with_plan = AsyncMock(return_value=(
        [SearchResult("text", "doc", "doc", "code_travail", 1, 1., 0, .5)],
        [plan.query_original],
    ))
    agent._fetch_identifiers = AsyncMock(side_effect=RetrievalError("lookup_failed"))
    if stage == "hybrid":
        agent._search_with_plan.side_effect = RetrievalError("search_branch_failed")
    rows, _, trace = await agent.prepare_context(plan.query_original, "org", search_plan=plan)
    assert rows == []
    assert trace.error == "search_retrieval_error"
    assert trace.search_plan["planner_raw_response"] == "  raw plan\n"
    assert search_feedback(trace)["warnings"]
    agent.reranker.rerank.assert_not_awaited()


async def test_public_and_sandbox_report_failure_without_generation(client, manager_user, monkeypatch):
    import json
    from decimal import Decimal

    from sqlalchemy import select

    from app.api import admin_quality, public
    from app.models.organisation import Organisation
    from app.models.user import User
    from app.rag.agent import RagTrace
    from app.rag.intent_router import Intent, IntentResult
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        org = Organisation(name="Failure test")
        db.add(org)
        await db.flush()
        org_id = org.id
        user_id = (await db.execute(select(User.id).where(User.email == manager_user["email"]))).scalar_one()
        await db.commit()

    raw = "  original plan\n"
    trace = RagTrace(query_original="question", error="search_retrieval_error",
                     search_plan={"planner_raw_response": raw},
                     search_plan_validation={"branches": [{"status": "ok"}, {"status": "error"}]})
    prepared = AsyncMock(return_value=([], "question", trace))
    generate = MagicMock(side_effect=AssertionError("generation must not run"))
    monkeypatch.setattr(RAGAgent, "prepare_context", prepared)
    monkeypatch.setattr(RAGAgent, "stream_generate", generate)
    monkeypatch.setattr(public, "async_session_factory", test_session_factory)
    monkeypatch.setattr(public.settings, "demo_enabled", True)
    monkeypatch.setattr(public, "_verify_turnstile", AsyncMock(return_value=True))
    monkeypatch.setattr(public, "_demo_rate_limit_ok", AsyncMock(return_value=True))
    monkeypatch.setattr(public, "_resolve_demo_ids", AsyncMock(return_value=(org_id, user_id)))
    monkeypatch.setattr(public, "_demo_spend_today_usd", AsyncMock(return_value=Decimal(0)))
    monkeypatch.setattr(public, "classify_intent", AsyncMock(return_value=IntentResult(Intent.LEGAL_QUESTION, static_answer=None, via="test")))
    response = await client.post("/api/v1/public/ask", json={"message": "Quelle règle du travail faut-il appliquer à cette situation ?"})
    assert response.status_code == 200, response.text
    assert 'event: chat_error' in response.text
    assert 'search_retrieval_error' in response.text
    assert 'event: chat_delta' not in response.text
    payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert any(p.get('raw_response') == raw for p in payloads)
    # Even accidentally retained candidates must not bypass a technical error.
    prepared.return_value = ([object()], "question", trace)
    async with test_session_factory() as db:
        result = await admin_quality._run_sandbox_pipeline(db, "question", org_id, None, False)
    assert result.answer is None
    assert result.rag_trace['error'] == 'search_retrieval_error'
    assert result.rag_trace['search_plan']['planner_raw_response'] == raw
    generate.assert_not_called()
