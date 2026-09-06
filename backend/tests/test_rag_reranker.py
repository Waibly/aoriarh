from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.rag.reranker import (
    RerankingError,
    VoyageReranker,
    build_rerank_query,
    document_rerank_input,
)
from app.rag.search import SearchResult


def result(doc="doc", score=0.8, text="passage"):
    return SearchResult(text, doc, doc, "code_travail", 1, 1.0, 0, score)


async def test_raw_scores_and_inputs_are_preserved_including_territories():
    items = [result("Mayotte", text="Dispositions applicables à Mayotte"), result("national")]
    rr = VoyageReranker()
    rr._call_api = AsyncMock(
        return_value={
            "data": [
                {"index": 0, "relevance_score": 0.95},
                {"index": 1, "relevance_score": 0.6},
            ]
        }
    )
    ranked = await rr.rerank("À Mayotte ?", items)
    assert [r.score for r in ranked] == [0.95, 0.6]
    assert [r.score for r in items] == [0.8, 0.8]
    assert ranked[0] is not items[0]
    assert ranked[0].retrieval_score == 0.8
    assert ranked[0].rerank_score == 0.95
    rr._call_api.assert_awaited_once_with("À Mayotte ?", [document_rerank_input(r) for r in items])
    assert [r.text for r in ranked] == [r.text for r in items]


def test_rerank_context_keeps_question_and_excludes_unrelated_org_fields():
    import json
    question = "Question complète\navec plusieurs lignes"
    encoded = build_rerank_query(question, {"convention_collective": "CCN test",
                                          "secret": "not-for-provider"}, "autonome")
    data = json.loads(encoded.split("\n", 1)[1])
    assert data["question_originale"] == question
    assert data["contexte_organisation"] == {"convention_collective": "CCN test"}


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": []},
        {"data": [{"index": 0, "relevance_score": 0.2}]},
        {"data": [{"index": 0, "relevance_score": 0.2}, {"index": 0, "relevance_score": 0.8}]},
        {"data": [{"index": -1, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.8}]},
        {"data": [{"index": True, "relevance_score": 0.2}, {"index": 1, "relevance_score": 0.8}]},
        {
            "data": [
                {"index": 0, "relevance_score": float("nan")},
                {"index": 1, "relevance_score": 0.8},
            ]
        },
        {"data": [{"index": 0, "relevance_score": "0.2"}, {"index": 1, "relevance_score": 0.8}]},
        {"data": [None, None]},
        None,
    ],
)
async def test_invalid_contract_is_an_error_not_a_replacement(response):
    rr = VoyageReranker()
    rr._call_api = AsyncMock(return_value=response)
    items = [result("a"), result("b")]
    with pytest.raises(RerankingError):
        await rr.rerank("question", items)
    assert [r.score for r in items] == [0.8, 0.8]
    rr._call_api.assert_awaited_once()


async def test_failure_is_propagated_without_fallback():
    rr = VoyageReranker()
    rr._call_api = AsyncMock(side_effect=httpx.ConnectError("offline"))
    with pytest.raises(RerankingError, match="unavailable"):
        await rr.rerank("q", [result()])
    rr._call_api.assert_awaited_once()


async def test_single_candidate_is_actually_scored():
    rr = VoyageReranker()
    rr._call_api = AsyncMock(return_value={"data": [{"index": 0, "relevance_score": 0.1}]})
    assert (await rr.rerank("q", [result()]))[0].score == 0.1
    rr._call_api.assert_awaited_once()


async def test_empty_pool_does_not_call_service():
    rr = VoyageReranker()
    rr._call_api = AsyncMock()
    assert await rr.rerank("q", []) == []
    rr._call_api.assert_not_awaited()


@pytest.mark.parametrize("mode", ["429", "timeout", "success"])
async def test_bounded_transport_retries_and_no_input_truncation(mode):
    client = AsyncMock()
    request = httpx.Request("POST", "https://api.voyageai.com/v1/rerank")
    success = httpx.Response(200, request=request, json={"data": []})
    client.post.side_effect = (
        [httpx.TimeoutException("timeout")] * 3
        if mode == "timeout"
        else [httpx.Response(429, request=request)] * 3
        if mode == "429"
        else [success]
    )
    with (
        patch("app.rag.reranker.get_shared_async_client", return_value=client),
        patch("app.rag.reranker.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        if mode == "success":
            await VoyageReranker()._call_api("q", ["doc"])
        else:
            with pytest.raises((httpx.TimeoutException, httpx.HTTPStatusError)):
                await VoyageReranker()._call_api("q", ["doc"])
        assert client.post.await_count == (1 if mode == "success" else 3)
        assert sleep.await_count == (0 if mode == "success" else 2)
        assert client.post.call_args.kwargs["json"]["truncation"] is False
