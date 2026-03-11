from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.rag.reranker import VoyageReranker
from app.rag.search import SearchResult

_DUMMY_REQUEST = httpx.Request("POST", "https://api.voyageai.com/v1/rerank")


def _make_result(text: str, score: float, doc_id: str = "doc1", chunk: int = 0) -> SearchResult:
    return SearchResult(
        text=text,
        doc_name="test.pdf",
        document_id=doc_id,
        source_type="code_travail",
        norme_niveau=4,
        norme_poids=0.8,
        chunk_index=chunk,
        score=score,
    )


def _mock_rerank_response(indices_scores: list[tuple[int, float]]) -> dict:
    return {
        "data": [
            {"index": idx, "relevance_score": score}
            for idx, score in indices_scores
        ],
        "usage": {"total_tokens": 100},
    }


def _httpx_response(status_code: int, json_data: dict) -> httpx.Response:
    return httpx.Response(status_code, json=json_data, request=_DUMMY_REQUEST)


@pytest.fixture
def reranker():
    return VoyageReranker()


class TestVoyageReranker:
    @pytest.mark.asyncio
    async def test_rerank_sorts_by_relevance_score(self, reranker):
        results = [
            _make_result("chunk A", 0.5, "doc1", 0),
            _make_result("chunk B", 0.8, "doc2", 0),
            _make_result("chunk C", 0.3, "doc3", 0),
        ]

        mock_response = _httpx_response(
            200, _mock_rerank_response([(0, 0.2), (1, 0.9), (2, 0.6)]),
        )

        with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranked = await reranker.rerank("test query", results, top_k=3)

        assert len(reranked) == 3
        # Should be sorted: B (0.9), C (0.6), A (0.2)
        assert reranked[0].text == "chunk B"
        assert reranked[0].score == 0.9
        assert reranked[1].text == "chunk C"
        assert reranked[1].score == 0.6
        assert reranked[2].text == "chunk A"
        assert reranked[2].score == 0.2

    @pytest.mark.asyncio
    async def test_rerank_respects_top_k(self, reranker):
        results = [
            _make_result("chunk A", 0.5, "doc1", 0),
            _make_result("chunk B", 0.8, "doc2", 0),
            _make_result("chunk C", 0.3, "doc3", 0),
        ]

        mock_response = _httpx_response(
            200, _mock_rerank_response([(0, 0.2), (1, 0.9), (2, 0.6)]),
        )

        with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranked = await reranker.rerank("test query", results, top_k=2)

        assert len(reranked) == 2
        assert reranked[0].text == "chunk B"
        assert reranked[1].text == "chunk C"

    @pytest.mark.asyncio
    async def test_fallback_on_api_failure(self, reranker):
        results = [
            _make_result("chunk A", 0.9, "doc1", 0),
            _make_result("chunk B", 0.5, "doc2", 0),
            _make_result("chunk C", 0.3, "doc3", 0),
        ]

        with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection failed")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranked = await reranker.rerank("test query", results, top_k=2)

        # Fallback: return original results truncated
        assert len(reranked) == 2
        assert reranked[0].text == "chunk A"
        assert reranked[1].text == "chunk B"

    @pytest.mark.asyncio
    async def test_empty_results(self, reranker):
        reranked = await reranker.rerank("test query", [], top_k=5)
        assert reranked == []

    @pytest.mark.asyncio
    async def test_single_result(self, reranker):
        results = [_make_result("only chunk", 0.8)]
        reranked = await reranker.rerank("test query", results, top_k=5)
        assert len(reranked) == 1
        assert reranked[0].text == "only chunk"

    @pytest.mark.asyncio
    async def test_retry_on_429(self, reranker):
        results = [
            _make_result("chunk A", 0.5, "doc1", 0),
            _make_result("chunk B", 0.8, "doc2", 0),
        ]

        rate_limit_response = _httpx_response(429, {"error": "rate limited"})
        success_response = _httpx_response(
            200, _mock_rerank_response([(0, 0.7), (1, 0.3)]),
        )

        with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = [rate_limit_response, success_response]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch("app.rag.reranker.asyncio.sleep", new_callable=AsyncMock):
                reranked = await reranker.rerank("test query", results, top_k=2)

        assert len(reranked) == 2
        assert reranked[0].text == "chunk A"
        assert reranked[0].score == 0.7

    @pytest.mark.asyncio
    async def test_scores_updated_after_rerank(self, reranker):
        results = [
            _make_result("chunk A", 0.5, "doc1", 0),
            _make_result("chunk B", 0.3, "doc2", 0),
        ]

        mock_response = _httpx_response(
            200, _mock_rerank_response([(0, 0.95), (1, 0.15)]),
        )

        with patch("app.rag.reranker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            reranked = await reranker.rerank("test query", results, top_k=2)

        assert reranked[0].score == 0.95
        assert reranked[1].score == 0.15
