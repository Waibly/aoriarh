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
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class CorpusHealthResponse(BaseModel):
    """Snapshot of corpus state for the admin Corpus page.

    Used both for live progress tracking (during reindex / init runs)
    and for the daily health card. Single endpoint so the frontend can
    poll one URL on a 3s interval without hammering the API.
    """
    docs_by_status: dict[str, int]
    docs_by_source_type: dict[str, int]
    common_total: int
    pending_count: int
    indexing_count: int
    indexed_count: int
    error_count: int
    reserved_count: int
    recent_sync_errors: list[dict]
    last_sync_per_type: dict[str, dict | None]
    is_busy: bool


@router.get("/health", response_model=CorpusHealthResponse)
async def get_corpus_health(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> CorpusHealthResponse:
    """Health snapshot of the common corpus.

    Aggregates in a single query the data the admin Corpus page needs
    for both the live progress banner and the health card. Cheap to
    poll (~ms thanks to indexes on indexation_status and source_type).
    """
    # 1. Documents by status (common docs only)
    status_rows = (await db.execute(
        select(Document.indexation_status, func.count(Document.id))
        .where(Document.organisation_id.is_(None))
        .group_by(Document.indexation_status)
    )).all()
    docs_by_status = {row[0]: row[1] for row in status_rows}

    # 2. Documents by source_type (common only)
    type_rows = (await db.execute(
        select(Document.source_type, func.count(Document.id))
        .where(Document.organisation_id.is_(None))
        .group_by(Document.source_type)
        .order_by(desc(func.count(Document.id)))
    )).all()
    docs_by_source_type = {row[0]: row[1] for row in type_rows}

    # 3. Sync errors in the last 24h
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    error_logs = (await db.execute(
        select(SyncLog)
        .where(SyncLog.status == "error", SyncLog.started_at >= cutoff)
        .order_by(desc(SyncLog.started_at))
        .limit(20)
    )).scalars().all()
    recent_sync_errors = [
        {
            "id": str(log.id),
            "sync_type": log.sync_type,
            "started_at": log.started_at.isoformat(),
            "error_message": log.error_message,
            "duration_ms": log.duration_ms,
        }
        for log in error_logs
    ]

    # 4. Last sync per known type
    last_per_type: dict[str, dict | None] = {}
    for sync_type in ("kali", "ccn", "jurisprudence", "codes", "code_travail", "bocc"):
        row = (await db.execute(
            select(SyncLog)
            .where(SyncLog.sync_type == sync_type)
            .order_by(desc(SyncLog.started_at))
            .limit(1)
        )).scalar_one_or_none()
        last_per_type[sync_type] = (
            {
                "status": row.status,
                "started_at": row.started_at.isoformat(),
                "items_created": row.items_created,
                "items_fetched": row.items_fetched,
                "errors": row.errors,
            }
            if row else None
        )

    pending = docs_by_status.get("pending", 0)
    indexing = docs_by_status.get("indexing", 0)

    return CorpusHealthResponse(
        docs_by_status=docs_by_status,
        docs_by_source_type=docs_by_source_type,
        common_total=sum(docs_by_status.values()),
        pending_count=pending,
        indexing_count=indexing,
        indexed_count=docs_by_status.get("indexed", 0),
        error_count=docs_by_status.get("error", 0),
        reserved_count=docs_by_status.get("reserved", 0),
        recent_sync_errors=recent_sync_errors,
        last_sync_per_type=last_per_type,
        # is_busy : something is actively being processed by the worker
        is_busy=(pending + indexing) > 0,
    )


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
