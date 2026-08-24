"""Génération de posts LinkedIn sourcés pour l'équipe AORIA RH."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.limiter import limiter
from app.models.api_usage import ApiUsageLog
from app.models.user import User
from app.rag.agent import _OUT_OF_SCOPE_MARKER, RAGAgent
from app.rag.config import RAG_TIMEOUT_CONTEXT, RAG_TIMEOUT_STREAM_IDLE
from app.rag.pipeline import prepare_rag_context
from app.rag.search import SearchResult
from app.services.cost_tracker import cost_tracker

router = APIRouter()
logger = logging.getLogger(__name__)

_COMMON_CORPUS_ORG_ID = "00000000-0000-0000-0000-000000000000"
_LINKEDIN_MAX_EMPTY_RETRIES = 1
_JURISPRUDENCE_SOURCE_TYPES = {
    "arret_cour_cassation",
    "arret_cour_appel",
    "arret_conseil_etat",
    "decision_conseil_constitutionnel",
}


class LinkedinGenerateRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    topic: str = Field(..., min_length=3, max_length=5000)


class LinkedinGenerateResponse(BaseModel):
    post: str
    character_count: int
    sources: list[dict]
    rag_trace: dict
    cost_usd: float
    duration_ms: int


def _select_linkedin_editorial_results(
    results: list[SearchResult],
    *,
    max_documents: int = 5,
) -> list[SearchResult]:
    """Resserre le contexte transmis au modèle avant la rédaction."""

    grouped: dict[str, list[SearchResult]] = {}
    representatives: list[SearchResult] = []
    for result in results:
        document_id = result.document_id
        if document_id not in grouped:
            grouped[document_id] = []
            representatives.append(result)
        grouped[document_id].append(result)

    written_law = [
        result
        for result in representatives
        if result.source_type not in _JURISPRUDENCE_SOURCE_TYPES
    ]
    jurisprudence = [
        result for result in representatives if result.source_type in _JURISPRUDENCE_SOURCE_TYPES
    ]

    selected_ids: list[str] = []
    for result in written_law[:3] + jurisprudence[:2] + representatives:
        if result.document_id not in selected_ids:
            selected_ids.append(result.document_id)
        if len(selected_ids) == max_documents:
            break

    return [chunk for document_id in selected_ids for chunk in grouped[document_id]]


async def _draft_post(
    agent: RAGAgent,
    topic: str,
    results: list,
    *,
    reformulated: str,
    low_confidence: bool,
) -> str:
    """Retourne exactement le texte produit par le modèle, sans transformation."""

    chunks: list[str] = []
    stream = agent.stream_generate(
        topic,
        results,
        org_context=None,
        history=None,
        low_confidence=low_confidence,
        condensed_query=reformulated,
        answer_format=None,
        generation_mode="linkedin_post",
    )
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(
                    anext(stream),
                    timeout=RAG_TIMEOUT_STREAM_IDLE,
                )
            except StopAsyncIteration:
                break
            chunks.append(chunk)
    finally:
        await stream.aclose()
    return "".join(chunks)


async def _draft_post_with_empty_retry(
    agent: RAGAgent,
    topic: str,
    results: list,
    *,
    reformulated: str,
    low_confidence: bool,
) -> tuple[str, int]:
    """Retente une génération vide, sans traiter une sortie non vide."""

    empty_retry_count = 0
    while True:
        post = await _draft_post(
            agent,
            topic,
            results,
            reformulated=reformulated,
            low_confidence=low_confidence,
        )
        if post or empty_retry_count >= _LINKEDIN_MAX_EMPTY_RETRIES:
            return post, empty_retry_count
        empty_retry_count += 1
        logger.warning("LinkedIn generation returned an empty body; retrying with the same sources")


@router.post("/generate", response_model=LinkedinGenerateResponse)
@limiter.limit("10/minute")
async def generate_linkedin_post(
    body: LinkedinGenerateRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> LinkedinGenerateResponse:
    """Recherche dans le corpus commun puis renvoie la rédaction brute du modèle."""

    topic = body.topic.strip()
    run_id = uuid.uuid4()
    started_at = time.perf_counter()
    agent = RAGAgent()

    try:
        results, reformulated, rag_trace = await asyncio.wait_for(
            prepare_rag_context(
                agent,
                query=topic,
                organisation_id=_COMMON_CORPUS_ORG_ID,
                org_context=None,
                history=None,
                cited_sources=None,
                org_idcc_list=None,
                user_id=None,
                context_id=str(run_id),
                is_replay=True,
            ),
            timeout=RAG_TIMEOUT_CONTEXT,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="La recherche documentaire a expiré. Veuillez réessayer.",
        ) from exc

    if reformulated == _OUT_OF_SCOPE_MARKER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le sujet doit relever du droit social ou des ressources humaines.",
        )
    if not results:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucune source suffisamment pertinente n'a été trouvée pour ce sujet.",
        )

    editorial_results = _select_linkedin_editorial_results(results)
    formatted_sources = agent.format_sources(editorial_results)
    rag_trace.search_plan_usage["linkedin_editorial_documents"] = len(formatted_sources)

    try:
        post, empty_retry_count = await _draft_post_with_empty_retry(
            agent,
            topic,
            editorial_results,
            reformulated=reformulated,
            low_confidence=rag_trace.low_confidence,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="La rédaction du post a expiré. Veuillez réessayer.",
        ) from exc
    rag_trace.search_plan_usage["linkedin_empty_retry_count"] = empty_retry_count
    if not post:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "La rédaction n'a produit aucun texte après une nouvelle tentative. "
                "Veuillez réessayer."
            ),
        )

    sources = [dataclasses.asdict(source) for source in formatted_sources]
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    rag_trace.perf_ms["total"] = float(duration_ms)

    # Les écritures de coût sont asynchrones ; on les vide avant de calculer le
    # total de cette génération admin, sans jamais l'attribuer à un client.
    await cost_tracker.flush()
    cost_result = await db.execute(
        select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
            ApiUsageLog.context_id == run_id,
            ApiUsageLog.is_replay.is_(True),
        )
    )

    return LinkedinGenerateResponse(
        post=post,
        character_count=len(post),
        sources=sources,
        rag_trace=rag_trace.to_dict(),
        cost_usd=float(cost_result.scalar() or 0.0),
        duration_ms=duration_ms,
    )
