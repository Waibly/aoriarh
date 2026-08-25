"""Génération de posts LinkedIn sourcés pour l'équipe AORIA RH."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse, Response, StreamingResponse

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


def _sse_event(event: str, payload: dict) -> str:
    """Encode un événement SSE sans modifier les fragments de texte du modèle."""

    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/generate")
@limiter.limit("10/minute")
async def generate_linkedin_post(
    body: LinkedinGenerateRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Diffuse en SSE, avec un repli JSON pour les onglets ouverts avant migration."""

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
    sources = [dataclasses.asdict(source) for source in formatted_sources]

    async def generation_events():
        yield "linkedin_start", {"sources": sources}

        chunks: list[str] = []
        empty_retry_count = 0
        try:
            while True:
                emitted_text = False
                stream = agent.stream_generate(
                    topic,
                    editorial_results,
                    buffer_size=1,
                    org_context=None,
                    history=None,
                    low_confidence=rag_trace.low_confidence,
                    condensed_query=reformulated,
                    answer_format=(
                        rag_trace.search_plan.get("answer_format")
                        if rag_trace.search_plan
                        else None
                    ),
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
                        if chunk:
                            emitted_text = True
                            chunks.append(chunk)
                            yield "linkedin_delta", {"content": chunk}
                finally:
                    await stream.aclose()

                if emitted_text or empty_retry_count >= _LINKEDIN_MAX_EMPTY_RETRIES:
                    break
                empty_retry_count += 1
                logger.warning(
                    "LinkedIn generation returned an empty body; retrying with the same sources"
                )
        except TimeoutError:
            logger.warning("LinkedIn generation stream timed out", exc_info=True)
            post = "".join(chunks)
            yield (
                "linkedin_error",
                {
                    "message": "La rédaction du post a expiré. Le texte déjà reçu reste visible.",
                    "post": post,
                    "character_count": len(post),
                    "sources": sources,
                    "rag_trace": rag_trace.to_dict(),
                    "cost_usd": 0.0,
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
            return
        except Exception:
            logger.exception("LinkedIn generation stream failed")
            post = "".join(chunks)
            yield (
                "linkedin_error",
                {
                    "message": (
                        "La connexion au modèle a été interrompue. "
                        "Le texte déjà reçu reste visible."
                    ),
                    "post": post,
                    "character_count": len(post),
                    "sources": sources,
                    "rag_trace": rag_trace.to_dict(),
                    "cost_usd": 0.0,
                    "duration_ms": int((time.perf_counter() - started_at) * 1000),
                },
            )
            return

        rag_trace.search_plan_usage["linkedin_empty_retry_count"] = empty_retry_count
        if not chunks:
            yield (
                "linkedin_error",
                {
                    "message": (
                        "La rédaction n'a produit aucun texte après une nouvelle tentative. "
                        "Veuillez réessayer."
                    )
                },
            )
            return

        # Cette concaténation reconstitue strictement les fragments reçus ; elle
        # sert uniquement aux métadonnées finales et ne remplace jamais le flux.
        post = "".join(chunks)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        rag_trace.perf_ms["total"] = float(duration_ms)

        cost_usd = 0.0
        try:
            # Les écritures de coût sont asynchrones ; on les vide avant de
            # calculer le total de cette génération admin.
            await cost_tracker.flush()
            cost_result = await db.execute(
                select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
                    ApiUsageLog.context_id == run_id,
                    ApiUsageLog.is_replay.is_(True),
                )
            )
            cost_usd = float(cost_result.scalar() or 0.0)
        except Exception:
            # Un échec de télémétrie ne doit jamais masquer une génération LLM.
            logger.exception("Unable to calculate LinkedIn generation cost")

        yield (
            "linkedin_done",
            {
                "post": post,
                "character_count": len(post),
                "sources": sources,
                "rag_trace": rag_trace.to_dict(),
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
            },
        )

    if "text/event-stream" in request.headers.get("accept", ""):
        async def event_stream():
            async for event, payload in generation_events():
                yield _sse_event(event, payload)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Compatibilité temporaire : un onglet chargé avant le passage au SSE
    # appelle encore response.json(). Il reçoit donc la sortie LLM brute au
    # format historique au lieu d'une erreur de parsing visible.
    async for event, payload in generation_events():
        if event == "linkedin_done":
            return JSONResponse(content=jsonable_encoder(payload))
        if event == "linkedin_error":
            if payload.get("post"):
                return JSONResponse(content=jsonable_encoder(payload))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": payload["message"]},
            )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "La génération du post a été interrompue. Veuillez réessayer."},
    )
