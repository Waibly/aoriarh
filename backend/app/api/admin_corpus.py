"""Admin Corpus endpoints — unified utilities for the new fused Corpus page.

For now, only one endpoint :
- POST /admin/corpus/test-retrieval → runs retrieval (hybrid + rerank +
  parent expansion) without calling the LLM, for QA on the corpus.

The Corpus page reuses existing endpoints from admin_documents, admin_ccn,
admin_judilibre, admin_syncs for everything else (no breaking change).
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class TestRetrievalRequest(BaseModel):
    query: str
    organisation_id: uuid.UUID | None = None  # if None, only common docs


class TestRetrievalChunk(BaseModel):
    document_id: str
    doc_name: str
    chunk_index: int
    score: float
    source_type: str
    text_preview: str


class TestRetrievalResponse(BaseModel):
    query: str
    duration_ms: int
    chunks_hybrid: list[TestRetrievalChunk]
    chunks_reranked: list[TestRetrievalChunk]
    chunks_expanded: list[TestRetrievalChunk]


def _serialize(results, limit: int = 30, text_chars: int = 350) -> list[TestRetrievalChunk]:
    out: list[TestRetrievalChunk] = []
    for r in results[:limit]:
        out.append(
            TestRetrievalChunk(
                document_id=str(r.document_id),
                doc_name=(r.doc_name or "")[:160],
                chunk_index=int(r.chunk_index),
                score=round(float(r.score), 4),
                source_type=str(r.source_type or ""),
                text_preview=(r.text or "")[:text_chars],
            )
        )
    return out


@router.post("/test-retrieval", response_model=TestRetrievalResponse)
async def test_retrieval(
    body: TestRetrievalRequest,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> TestRetrievalResponse:
    """Run retrieval-only (no LLM) for QA on the corpus."""
    from app.rag.search import HybridSearch
    from app.rag.reranker import get_reranker
    from app.rag.parent_expansion import (
        expand_to_parents,
        detect_identifiers,
        fetch_by_identifiers,
    )
    from app.rag.config import TOP_K, RERANK_TOP_K

    if not body.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question vide",
        )

    org_id = str(body.organisation_id) if body.organisation_id else "common"
    se = HybridSearch()
    rk = get_reranker()
    se.set_cost_context(is_replay=True)
    rk.set_cost_context(is_replay=True)

    t0 = time.perf_counter()
    hybrid = await se.search(body.query, organisation_id=org_id, top_k=TOP_K * 2)

    # Identifier boost
    ids = detect_identifiers(body.query)
    if any(ids.values()):
        try:
            extra = fetch_by_identifiers(
                se.qdrant, ids, organisation_id=org_id, org_idcc_list=None
            )
            seen = {(r.document_id, r.chunk_index) for r in hybrid}
            for r in extra:
                key = (r.document_id, r.chunk_index)
                if key not in seen:
                    seen.add(key)
                    hybrid.insert(0, r)
        except Exception:
            logger.exception("[CORPUS-TEST] identifier boost failed")

    reranked = await rk.rerank(body.query, hybrid, top_k=RERANK_TOP_K)
    expanded = expand_to_parents(reranked, se.qdrant)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    return TestRetrievalResponse(
        query=body.query,
        duration_ms=duration_ms,
        chunks_hybrid=_serialize(hybrid, limit=30),
        chunks_reranked=_serialize(reranked, limit=15),
        chunks_expanded=_serialize(expanded, limit=15, text_chars=600),
    )
