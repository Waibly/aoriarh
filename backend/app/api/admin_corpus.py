"""Admin Corpus endpoints — unified utilities for the new fused Corpus page.

For now, only one endpoint :
- POST /admin/corpus/test-retrieval → runs the full RAG pipeline
  (retrieval + rerank + parent expansion) on the common corpus,
  WITHOUT calling the LLM. Returns the same payload shape as the
  Quality sandbox so the frontend can reuse InspectorBody.

The Corpus page reuses existing endpoints from admin_documents, admin_ccn,
admin_judilibre, admin_syncs for everything else (no breaking change).
"""
from __future__ import annotations

import dataclasses
import logging
import time

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


class TestRetrievalResponse(BaseModel):
    """Same shape as SandboxRunResponse so the frontend can use InspectorBody."""
    answer: str | None
    sources: list[dict]
    rag_trace: dict
    cost_usd: float
    duration_ms: int


@router.post("/test-retrieval", response_model=TestRetrievalResponse)
async def test_retrieval(
    body: TestRetrievalRequest,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> TestRetrievalResponse:
    """Run the full RAG retrieval pipeline against the common corpus only.

    Same code path as the Quality sandbox (so the frontend can reuse
    InspectorBody) but :
    - organisation_id = '__corpus_test__' (no org docs are matched, only
      the common pool — code, jurisprudence, doctrine, etc.)
    - skip generation (no LLM call, no answer text)
    - tagged is_replay=True so the cost doesn't appear in client metrics
    """
    if not body.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question vide",
        )

    from app.rag.agent import RAGAgent

    agent = RAGAgent()
    t_start = time.perf_counter()

    # Use a synthetic org id that won't match any real org documents — the
    # search engine's `should=[org_id, "common"]` filter will then only
    # return common docs. We pass an UUID-shaped string so the type check
    # in HybridSearch doesn't blow up.
    fake_org_id = "00000000-0000-0000-0000-000000000000"

    results, reformulated, rag_trace = await agent.prepare_context(
        query=body.query.strip(),
        organisation_id=fake_org_id,
        org_context=None,
        history=None,
        org_idcc_list=None,
        user_id=None,
        conversation_id=None,
        is_replay=True,
    )

    sources_dicts: list[dict] = []
    if results:
        sources = agent.format_sources(results)
        sources_dicts = [dataclasses.asdict(s) for s in sources]

    duration_ms = int((time.perf_counter() - t_start) * 1000)
    rag_trace.perf_ms["total"] = float(duration_ms)

    # Sum costs for this run (will be 0 unless embeddings ran)
    from app.models.api_usage import ApiUsageLog
    from sqlalchemy import func, select

    cost_q = await db.execute(
        select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
            ApiUsageLog.is_replay.is_(True),
            ApiUsageLog.created_at >= __import__("datetime").datetime.now(
                __import__("datetime").UTC
            )
            - __import__("datetime").timedelta(seconds=duration_ms / 1000 + 5),
        )
    )
    cost_usd = float(cost_q.scalar() or 0.0)

    return TestRetrievalResponse(
        answer=None,
        sources=sources_dicts,
        rag_trace=rag_trace.to_dict(),
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )
