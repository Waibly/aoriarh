import asyncio
import logging
import time

import httpx

from app.core.config import settings
from app.rag.config import RERANK_MODEL
from app.rag.search import SearchResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0


class VoyageReranker:
    """Cross-encoder reranker using Voyage AI rerank-2."""

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Rerank search results using Voyage AI cross-encoder.

        Falls back to truncated original results if the API call fails.
        """
        if len(results) <= 1:
            return results[:top_k]

        documents = [r.text for r in results]
        t0 = time.perf_counter()

        try:
            rerank_response = await self._call_api(query, documents)
        except Exception:
            logger.exception("Reranker API failed, returning original results")
            return results[:top_k]

        elapsed = (time.perf_counter() - t0) * 1000
        tokens = rerank_response.get("usage", {}).get("total_tokens", "?")
        logger.info(
            "[PERF] Reranking (Voyage AI %s) %.0fms | %s tokens | %d→%d results",
            RERANK_MODEL, elapsed, tokens, len(results), min(top_k, len(results)),
        )

        # Map reranked scores back to SearchResult objects
        ranked_data = rerank_response.get("data", [])
        for item in ranked_data:
            idx = item["index"]
            results[idx].score = item["relevance_score"]

        # Sort by relevance_score descending
        reranked = sorted(results, key=lambda r: r.score, reverse=True)
        return reranked[:top_k]

    async def _call_api(self, query: str, documents: list[str]) -> dict:
        """Call Voyage AI rerank API with exponential backoff retry on 429."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        "https://api.voyageai.com/v1/rerank",
                        headers={
                            "Authorization": f"Bearer {settings.voyage_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "query": query,
                            "documents": documents,
                            "model": RERANK_MODEL,
                            "truncation": True,
                        },
                    )
                    if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "[PERF] Voyage AI rerank rate limit (429), retrying in %.1fs...",
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    return response.json()
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "[PERF] Voyage AI rerank timeout, retrying in %.1fs...",
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise last_error or RuntimeError("Voyage AI rerank: max retries exceeded")


# Module-level singleton
_reranker = VoyageReranker()


def get_reranker() -> VoyageReranker:
    return _reranker
