import dataclasses
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import RAGAgent
from app.schemas.conversation import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationRead,
    ConversationReadWithMessages,
    MessageFeedback,
    MessageRead,
)
from app.core.limiter import limiter
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    data: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationRead:
    service = ConversationService(db)
    conversation = await service.create_conversation(
        organisation_id=data.organisation_id,
        user=user,
        title=data.title,
    )
    return conversation  # type: ignore[return-value]


@router.get("/", response_model=list[ConversationRead])
async def list_conversations(
    organisation_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationRead]:
    service = ConversationService(db)
    conversations = await service.list_conversations(
        organisation_id=organisation_id,
        user=user,
    )
    return conversations  # type: ignore[return-value]


@router.get("/{conversation_id}", response_model=ConversationReadWithMessages)
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationReadWithMessages:
    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=conversation_id,
        user=user,
    )
    return conversation  # type: ignore[return-value]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ConversationService(db)
    await service.delete_conversation(
        conversation_id=conversation_id,
        user=user,
    )


@router.patch("/messages/{message_id}/feedback", response_model=MessageRead)
async def update_message_feedback(
    message_id: uuid.UUID,
    data: MessageFeedback,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    service = ConversationService(db)
    message = await service.update_message_feedback(
        message_id=message_id,
        user=user,
        feedback=data.feedback,
        comment=data.comment,
    )
    return message  # type: ignore[return-value]


@router.post("/{conversation_id}/chat", response_model=ChatResponse)
@limiter.limit("15/minute")
async def chat(
    conversation_id: uuid.UUID,
    data: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    service = ConversationService(db)

    # 1. Verify access
    conversation = await service.get_conversation(
        conversation_id=conversation_id,
        user=user,
    )

    # 2. Load org context for RAG
    org_context = await _load_org_context(db, conversation.organisation_id)
    if org_context is not None:
        org_context["profil_metier"] = user.profil_metier

    # 3. Call RAG agent FIRST — nothing saved yet
    history = [
        {"role": m.role, "content": m.content}
        for m in conversation.messages[-6:]
    ]
    agent = RAGAgent()
    rag_response = await agent.run(
        query=data.message,
        organisation_id=str(conversation.organisation_id),
        org_context=org_context,
        history=history if history else None,
        user_id=str(user.id),
        conversation_id=str(conversation_id),
    )

    # 4. If RAG failed, return 503 — nothing in DB
    if rag_response.is_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=rag_response.answer,
        )

    # 5. RAG succeeded — save user message + assistant response
    sources_dicts = [
        dataclasses.asdict(s) for s in rag_response.sources
    ] if rag_response.sources else None

    user_message = await service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
    )
    assistant_message = await service.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content=rag_response.answer,
        sources=sources_dicts,
    )

    # 6. Auto-generate title from first message
    if conversation.title is None:
        title = data.message[:100].strip()
        if len(data.message) > 100:
            title = title.rsplit(" ", 1)[0] + "…"
        await service.update_title(conversation_id, title)

    return ChatResponse(
        message=user_message,  # type: ignore[arg-type]
        answer=assistant_message,  # type: ignore[arg-type]
    )


async def _load_org_context(
    db: AsyncSession, organisation_id: uuid.UUID
) -> dict[str, str | None] | None:
    """Load organisation profile for RAG context injection."""
    result = await db.execute(
        select(Organisation).where(Organisation.id == organisation_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return None
    ctx = {
        "nom": org.name,
        "forme_juridique": org.forme_juridique,
        "taille": org.taille,
        "convention_collective": org.convention_collective,
        "secteur_activite": org.secteur_activite,
    }
    return ctx


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{conversation_id}/chat/stream")
@limiter.limit("15/minute")
async def chat_stream(
    conversation_id: uuid.UUID,
    data: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    service = ConversationService(db)

    # 1. Verify access
    conversation = await service.get_conversation(
        conversation_id=conversation_id,
        user=user,
    )

    # 2. Load org context for RAG
    org_context = await _load_org_context(db, conversation.organisation_id)
    if org_context is not None:
        org_context["profil_metier"] = user.profil_metier

    async def sse_generator():  # noqa: C901
        t_total = time.perf_counter()
        agent = RAGAgent()
        history = [
            {"role": m.role, "content": m.content}
            for m in conversation.messages[-6:]
        ]
        try:
            # 3. Prepare context (steps 0-5: condensation, reformulation, search, rerank)
            results, reformulated = await agent.prepare_context(
                query=data.message,
                organisation_id=str(conversation.organisation_id),
                org_context=org_context,
                history=history if history else None,
                user_id=str(user.id),
                conversation_id=str(conversation_id),
            )

            if not results:
                yield _sse_event("chat_error", {
                    "error": "no_results",
                    "message": (
                        "Je n'ai pas trouvé de documents pertinents dans "
                        "votre base documentaire pour répondre à cette question."
                    ),
                })
                return

            # 3. Send sources before generation starts
            sources = agent.format_sources(results)
            sources_dicts = [dataclasses.asdict(s) for s in sources]
            yield _sse_event("chat_sources", {"sources": sources_dicts})
            t_sources = time.perf_counter()
            logger.info(
                "[PERF] Sources sent to client %.0fms after request",
                (t_sources - t_total) * 1000,
            )

            # 4. Stream LLM generation
            if await request.is_disconnected():
                return

            full_answer = ""
            try:
                async for chunk in agent.stream_generate(data.message, results, org_context=org_context):
                    if await request.is_disconnected():
                        logger.info("Client disconnected during streaming")
                        return
                    full_answer += chunk
                    yield _sse_event("chat_delta", {"content": chunk})
            except Exception as stream_exc:
                logger.warning(
                    "Stream generation interrupted after %d chars: %s",
                    len(full_answer), stream_exc,
                )
                if not full_answer:
                    # Nothing generated — send error
                    yield _sse_event("chat_error", {
                        "error": "server_error",
                        "message": (
                            "Une erreur est survenue lors de la génération "
                            "de la réponse. Veuillez réessayer."
                        ),
                    })
                    return
                # Partial content exists — continue to save what we have

            t_stream_done = time.perf_counter()

            # 5. Save messages to DB (user + assistant)
            user_message = await service.add_message(
                conversation_id=conversation_id,
                role="user",
                content=data.message,
            )
            assistant_message = await service.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_answer,
                sources=sources_dicts if sources_dicts else None,
            )

            # 6. Auto-generate title
            if conversation.title is None:
                title = data.message[:100].strip()
                if len(data.message) > 100:
                    title = title.rsplit(" ", 1)[0] + "…"
                await service.update_title(conversation_id, title)

            t_db = time.perf_counter()
            logger.info(
                "[PERF] DB save %.0fms", (t_db - t_stream_done) * 1000,
            )

            # 7. Send done event with IDs
            yield _sse_event("chat_done", {
                "message_id": str(user_message.id),
                "answer_id": str(assistant_message.id),
            })

            logger.info(
                "[PERF] ══ TOTAL request %.0fms (context %.0fms + streaming %.0fms + db %.0fms)",
                (t_db - t_total) * 1000,
                (t_sources - t_total) * 1000,
                (t_stream_done - t_sources) * 1000,
                (t_db - t_stream_done) * 1000,
            )

        except Exception as exc:
            logger.exception(
                "SSE streaming error for conversation %s", conversation_id,
            )
            # Detect OpenAI quota/auth errors for a clear message
            exc_str = str(exc).lower()
            if "insufficient_quota" in exc_str or "exceeded" in exc_str:
                error_msg = (
                    "Clé API OpenAI : quota dépassé ou crédits insuffisants. "
                    "Vérifiez votre compte OpenAI."
                )
            elif "invalid_api_key" in exc_str or "unauthorized" in exc_str:
                error_msg = (
                    "Clé API OpenAI invalide. "
                    "Vérifiez la configuration du serveur."
                )
            else:
                error_msg = (
                    "Une erreur est survenue lors du traitement "
                    "de votre question. Veuillez réessayer."
                )
            yield _sse_event("chat_error", {
                "error": "server_error",
                "message": error_msg,
            })

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
