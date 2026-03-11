import asyncio
import logging
import threading
import time
from dataclasses import dataclass

import httpx
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FusionQuery,
    MatchValue,
    Prefetch,
    SparseVector,
)

from app.core.config import settings
from app.rag.config import EMBEDDING_MODEL, TOP_K
from app.rag.qdrant_store import COLLECTION_NAME, get_qdrant_client

logger = logging.getLogger(__name__)

# --- Singletons (loaded once at module level) ---

_sparse_model = None
_SPARSE_LOCK = threading.Lock()

# Retry config for Voyage AI
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0


def _get_sparse_model():
    """Return a module-level singleton BM25 model (thread-safe)."""
    global _sparse_model
    if _sparse_model is not None:
        return _sparse_model
    with _SPARSE_LOCK:
        # Double-checked locking: re-check after acquiring lock
        if _sparse_model is None:
            from fastembed import SparseTextEmbedding

            _sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _sparse_model


@dataclass
class SearchResult:
    """A single search result from the hybrid search."""

    text: str
    doc_name: str
    document_id: str
    source_type: str
    norme_niveau: int
    norme_poids: float
    chunk_index: int
    score: float
    # Jurisprudence metadata (optional)
    juridiction: str | None = None
    chambre: str | None = None
    formation: str | None = None
    numero_pourvoi: str | None = None
    date_decision: str | None = None
    solution: str | None = None
    publication: str | None = None


class HybridSearch:
    """Recherche hybride dans Qdrant (dense + sparse) avec filtrage par organisation."""

    def __init__(self) -> None:
        self.qdrant = get_qdrant_client()

    async def search(
        self,
        query: str,
        organisation_id: str,
        top_k: int = TOP_K,
    ) -> list[SearchResult]:
        """Execute a hybrid search combining dense and sparse vectors."""
        t0 = time.perf_counter()

        # 1. Encode query — dense (Voyage AI) + sparse (BM25) in parallel
        dense_task = self._encode_dense(query)
        sparse_task = asyncio.to_thread(self._encode_sparse_sync, query)
        dense_embedding, sparse_vector = await asyncio.gather(
            dense_task, sparse_task,
        )

        t1 = time.perf_counter()
        logger.info("[PERF] Encoding (dense+sparse parallel) %.0fms", (t1 - t0) * 1000)

        # 2. Build organisation filter (also include common documents)
        org_filter = Filter(
            should=[
                FieldCondition(
                    key="organisation_id",
                    match=MatchValue(value=organisation_id),
                ),
                FieldCondition(
                    key="organisation_id",
                    match=MatchValue(value="common"),
                ),
            ],
        )

        # 3. Hybrid query with RRF fusion via prefetch
        prefetch_dense = Prefetch(
            query=dense_embedding,
            using="dense",
            limit=top_k * 2,
            filter=org_filter,
        )
        prefetch_sparse = Prefetch(
            query=SparseVector(
                indices=sparse_vector["indices"],
                values=sparse_vector["values"],
            ),
            using="sparse-bm25",
            limit=top_k * 2,
            filter=org_filter,
        )

        results = self.qdrant.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[prefetch_dense, prefetch_sparse],
            query=FusionQuery(fusion="rrf"),
            limit=top_k,
            with_payload=True,
        )

        t2 = time.perf_counter()
        logger.info("[PERF] Qdrant query %.0fms (%d points)", (t2 - t1) * 1000, len(results.points))

        # 4. Build SearchResult list and apply norme_poids weighting
        search_results: list[SearchResult] = []
        for point in results.points:
            payload = point.payload or {}
            norme_poids = float(payload.get("norme_poids", 0.5))
            rrf_score = point.score if point.score is not None else 0.0
            weighted_score = rrf_score * (0.6 + 0.4 * norme_poids)

            search_results.append(
                SearchResult(
                    text=payload.get("text", ""),
                    doc_name=payload.get("doc_name", ""),
                    document_id=payload.get("document_id", ""),
                    source_type=payload.get("source_type", ""),
                    norme_niveau=int(payload.get("norme_niveau", 9)),
                    norme_poids=norme_poids,
                    chunk_index=int(payload.get("chunk_index", 0)),
                    score=weighted_score,
                    juridiction=payload.get("juridiction"),
                    chambre=payload.get("chambre"),
                    formation=payload.get("formation"),
                    numero_pourvoi=payload.get("numero_pourvoi"),
                    date_decision=payload.get("date_decision"),
                    solution=payload.get("solution"),
                    publication=payload.get("publication"),
                )
            )

        # 5. Re-sort by weighted score and return top_k
        search_results.sort(key=lambda r: r.score, reverse=True)
        return search_results[:top_k]

    async def _encode_dense(self, text: str) -> list[float]:
        """Encode text to dense vector using Voyage AI API with retry."""
        t_start = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        "https://api.voyageai.com/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {settings.voyage_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "input": [text],
                            "model": EMBEDDING_MODEL,
                            "input_type": "query",
                        },
                    )
                    if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "[PERF] Voyage AI rate limit (429), retrying in %.1fs...", delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    logger.info(
                        "[PERF]   ├─ Dense embedding (Voyage AI) %.0fms (attempt %d)",
                        (time.perf_counter() - t_start) * 1000, attempt + 1,
                    )
                    return data["data"][0]["embedding"]
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < _MAX_RETRIES - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "[PERF] Voyage AI timeout, retrying in %.1fs...", delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        raise last_error or RuntimeError("Voyage AI: max retries exceeded")

    def _encode_sparse_sync(self, text: str) -> dict:
        """Encode text to sparse BM25 vector (synchronous, run via to_thread)."""
        t_start = time.perf_counter()
        model = _get_sparse_model()
        t_model = time.perf_counter()
        results = list(model.embed([text]))
        t_end = time.perf_counter()
        logger.info(
            "[PERF]   └─ Sparse embedding (BM25) %.0fms (model load %.0fms, encode %.0fms)",
            (t_end - t_start) * 1000,
            (t_model - t_start) * 1000,
            (t_end - t_model) * 1000,
        )
        return {
            "indices": results[0].indices.tolist(),
            "values": results[0].values.tolist(),
        }
