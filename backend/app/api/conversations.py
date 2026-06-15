import dataclasses
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from pydantic import BaseModel

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.conversation import Message
from app.models.document import Document
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import (
    RAGAgent,
    _OUT_OF_SCOPE_MARKER,
    _OUT_OF_SCOPE_ANSWER,
    _SOURCE_TYPE_LABELS,
)
from app.rag.intent_router import classify_intent, Intent
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
from app.services.billing_service import BillingService
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


@router.delete("/", status_code=status.HTTP_200_OK)
async def hide_all_conversations(
    organisation_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete (hide) ALL the user's conversations in this organisation.

    The conversations and their messages stay in DB so analytics, costs
    and admin audit keep working — only the user-facing chat sidebar is
    cleared. Returns the number of conversations hidden.
    """
    service = ConversationService(db)
    n = await service.hide_all_conversations(
        organisation_id=organisation_id,
        user=user,
    )
    return {"hidden": n}


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


class SourceFullContentResponse(BaseModel):
    document_id: str
    name: str
    source_type: str
    content: str
    size_bytes: int


@router.get(
    "/sources/{document_id}/full-content",
    response_model=SourceFullContentResponse,
)
async def get_source_full_content(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceFullContentResponse:
    """Return the full text content of a source document.

    Used by the chat source dialog "Voir le document complet" button
    when a source was truncated to 9000 characters in the retrieval
    payload. Access rules :

    - Common documents (organisation_id IS NULL) : readable by any
      authenticated user (the whole legal corpus is common).
    - Org documents : user must be a member of the owning org.
    """
    doc = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()

    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document non trouvé",
        )

    if doc.organisation_id is not None and user.role != "admin":
        from app.core.dependencies import verify_org_membership
        membership = await verify_org_membership(doc.organisation_id, user, db)
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès non autorisé à ce document",
            )

    if not doc.storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contenu indisponible pour ce document",
        )

    from app.services.storage_service import StorageService
    storage = StorageService()
    try:
        file_bytes = storage.get_file_bytes(doc.storage_path)
    except Exception as exc:
        logger.warning("Failed to fetch storage content for doc %s: %s", doc.id, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contenu introuvable en stockage",
        )

    # Only text-like formats can be rendered inline. PDF/DOCX are binary
    # and handled by the download endpoint, not this one.
    fmt = (doc.file_format or "").lower()
    if fmt in ("pdf", "docx", "xlsx", "pptx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Format '{fmt}' non affichable inline. "
                "Utilisez le téléchargement du document."
            ),
        )

    try:
        content = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = file_bytes.decode("latin-1", errors="replace")

    return SourceFullContentResponse(
        document_id=str(doc.id),
        name=doc.name,
        source_type=doc.source_type,
        content=content,
        size_bytes=len(file_bytes),
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


@router.post("/messages/{message_id}/fiche")
@limiter.limit("10/minute")
async def generate_fiche(
    message_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Transforme une réponse de l'assistant en fiche pratique PDF imprimable.

    Met en forme la réponse déjà générée (pas de nouvelle génération RAG) via
    un appel LLM dédié, puis rend un PDF à la charte AORIA RH. Renvoie 422 si la
    réponse ne se prête pas à une fiche générale (cas particulier).
    """
    from datetime import datetime

    from app.services.fiche_service import build_fiche

    message = (await db.execute(
        select(Message).where(Message.id == message_id)
    )).scalar_one_or_none()

    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    # Vérifie l'accès via la conversation (cloisonnement multi-tenant).
    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )

    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut être transformée en fiche.",
        )

    # Retrouve la question (dernier message utilisateur avant cette réponse).
    question = ""
    for m in conversation.messages:
        if m.created_at >= message.created_at:
            break
        if m.role == "user":
            question = m.content

    org = (await db.execute(
        select(Organisation.name).where(Organisation.id == conversation.organisation_id)
    )).scalar_one_or_none()

    sources = message.sources if isinstance(message.sources, list) else []

    try:
        result = await build_fiche(
            question=question,
            answer_markdown=message.content,
            sources=sources,
            generated_at=datetime.now(),
            org_name=org,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
        )
    except Exception:
        logger.exception("Échec de génération de fiche pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La génération de la fiche a échoué. Veuillez réessayer.",
        )

    if not result.eligible or result.pdf_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.reason or "Cette réponse ne se prête pas à une fiche pratique.",
        )

    return Response(
        content=result.pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
        },
    )


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
    billing = BillingService(db)

    # 1. Verify access
    conversation = await service.get_conversation(
        conversation_id=conversation_id,
        user=user,
    )

    # 1b. Enforce quota / plan lifecycle (raises 402 if expired/suspended).
    account = await billing.get_account_for_organisation(conversation.organisation_id)
    await billing.check_question_quota(account)

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

    # 3a. Intent router : court-circuit RAG pour les meta-questions
    intent_result = await classify_intent(
        query=data.message,
        db=db,
        llm=agent.llm,
        organisation_id=conversation.organisation_id,
    )
    if intent_result.static_answer is not None:
        logger.info("[INTENT] %s via %s — court-circuit RAG", intent_result.intent.value, intent_result.via)
        meta_user = await service.add_message(
            conversation_id=conversation_id,
            role="user",
            content=data.message,
        )
        meta_assistant = await service.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=intent_result.static_answer,
        )
        if conversation.title is None:
            title = data.message[:100].strip()
            if len(data.message) > 100:
                title = title.rsplit(" ", 1)[0] + "…"
            await service.update_title(conversation_id, title)
        await db.commit()
        return ChatResponse(
            message=meta_user,  # type: ignore[arg-type]
            answer=meta_assistant,  # type: ignore[arg-type]
        )

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

    # 5b. Increment the monthly question counter (fair-use: never blocks).
    await billing.increment_question_count(account)

    # 6. Auto-generate title from first message
    if conversation.title is None:
        title = data.message[:100].strip()
        if len(data.message) > 100:
            title = title.rsplit(" ", 1)[0] + "…"
        await service.update_title(conversation_id, title)

    await db.commit()

    return ChatResponse(
        message=user_message,  # type: ignore[arg-type]
        answer=assistant_message,  # type: ignore[arg-type]
    )


async def _load_org_context(
    db: AsyncSession, organisation_id: uuid.UUID
) -> dict[str, str | bool | None] | None:
    """Load organisation profile for RAG context injection."""
    from app.models.ccn import CcnReference, OrganisationConvention

    result = await db.execute(
        select(Organisation).where(Organisation.id == organisation_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return None

    # Get installed CCNs with their names
    ccn_result = await db.execute(
        select(OrganisationConvention.idcc, CcnReference.titre)
        .join(CcnReference, CcnReference.idcc == OrganisationConvention.idcc)
        .where(
            OrganisationConvention.organisation_id == organisation_id,
            OrganisationConvention.status.in_(["ready", "indexing", "fetching"]),
        )
    )
    installed_ccns = ccn_result.all()

    # Build convention_collective string from installed CCNs if not manually set
    convention_str = org.convention_collective
    if not convention_str and installed_ccns:
        convention_str = "; ".join(
            f"{row.titre} (IDCC {row.idcc})" for row in installed_ccns
        )

    ctx: dict[str, str | bool | None] = {
        "nom": org.name,
        "forme_juridique": org.forme_juridique,
        "taille": org.taille,
        "convention_collective": convention_str,
        "secteur_activite": org.secteur_activite,
        "not_subject_to_ccn": bool(org.not_subject_to_ccn),
    }
    return ctx


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# --- Recherche documentaire (admin v1) -------------------------------------
# Recherche de sources sans génération LLM : on lance le pipeline de retrieval
# (expansion → recherche → rerank → expansion parent) et on renvoie les chunks
# remontés, un par carte. Pas de génération : coût quasi nul. Réservé aux admins
# pour cette v1.


class DocumentSearchRequest(BaseModel):
    organisation_id: uuid.UUID
    query: str


class DocumentSearchCard(BaseModel):
    document_id: str
    document_name: str
    source_type: str
    source_type_label: str
    norme_niveau: int
    score: float
    excerpt: str
    article_nums: list[str] | None = None
    section_path: str | None = None
    juridiction: str | None = None
    chambre: str | None = None
    numero_pourvoi: str | None = None
    date_decision: str | None = None
    solution: str | None = None
    publication: str | None = None


class DocumentSearchResponse(BaseModel):
    query_used: str
    variants: list[str]
    out_of_scope: bool
    results: list[DocumentSearchCard]


@router.post("/search", response_model=DocumentSearchResponse)
@limiter.limit("30/minute")
async def search_documents(
    data: DocumentSearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentSearchResponse:
    """Recherche documentaire sans génération (cartes de sources). Admin v1."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Fonctionnalité réservée aux administrateurs.",
        )

    org_context = await _load_org_context(db, data.organisation_id)
    if org_context is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation introuvable.",
        )
    org_context["profil_metier"] = user.profil_metier

    # Liste IDCC de l'org pour filtrer la recherche (même logique que le chat).
    if org_context.get("not_subject_to_ccn"):
        org_idcc_list = None
    else:
        from app.models.ccn import OrganisationConvention
        idcc_result = await db.execute(
            select(OrganisationConvention.idcc).where(
                OrganisationConvention.organisation_id == data.organisation_id,
                OrganisationConvention.use_custom.is_(False),
            )
        )
        org_idcc_list = [r[0] for r in idcc_result.all()] or None

    agent = RAGAgent()
    question_id = uuid.uuid4()  # contexte de coût (embeddings + rerank + expansion)
    results, reformulated, rag_trace = await agent.prepare_context(
        query=data.query,
        organisation_id=str(data.organisation_id),
        org_context=org_context,
        history=None,
        cited_sources=None,
        org_idcc_list=org_idcc_list,
        user_id=str(user.id),
        conversation_id=str(question_id),
    )

    if reformulated == _OUT_OF_SCOPE_MARKER:
        return DocumentSearchResponse(
            query_used=data.query, variants=[], out_of_scope=True, results=[],
        )

    cards: list[DocumentSearchCard] = []
    seen: set[tuple[str, int]] = set()
    for r in results:
        key = (r.document_id, r.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        passage = (r.seed_text or r.text or "").strip()
        if not passage:
            continue
        cards.append(
            DocumentSearchCard(
                document_id=r.document_id,
                document_name=r.doc_name,
                source_type=r.source_type,
                source_type_label=_SOURCE_TYPE_LABELS.get(r.source_type, r.source_type),
                norme_niveau=r.norme_niveau,
                score=round(float(r.score or 0.0), 4),
                excerpt=passage,
                article_nums=r.article_nums,
                section_path=r.section_path,
                juridiction=r.juridiction,
                chambre=r.chambre,
                numero_pourvoi=r.numero_pourvoi,
                date_decision=r.date_decision,
                solution=r.solution,
                publication=r.publication,
            )
        )

    cards.sort(key=lambda c: c.score, reverse=True)
    return DocumentSearchResponse(
        query_used=reformulated or data.query,
        variants=list(rag_trace.variants or []),
        out_of_scope=False,
        results=cards,
    )


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
    billing = BillingService(db)

    # 1. Verify access
    conversation = await service.get_conversation(
        conversation_id=conversation_id,
        user=user,
    )

    # 1b. Enforce quota / plan lifecycle (raises 402 if expired/suspended).
    account = await billing.get_account_for_organisation(conversation.organisation_id)
    await billing.check_question_quota(account)

    # 2. Load org context for RAG
    org_context = await _load_org_context(db, conversation.organisation_id)
    if org_context is not None:
        org_context["profil_metier"] = user.profil_metier

    async def sse_generator():  # noqa: C901
        t_total = time.perf_counter()
        agent = RAGAgent()
        recent_messages = conversation.messages[-6:]
        history = [
            {"role": m.role, "content": m.content}
            for m in recent_messages
        ]
        # Extract source names from recent assistant messages for condensation
        cited_sources: list[str] = []
        for m in recent_messages:
            if m.role == "assistant" and m.sources:
                for src in m.sources:
                    name = src.get("document_name") if isinstance(src, dict) else None
                    if name and name not in cited_sources:
                        cited_sources.append(name)
        try:
            # 2a. INTENT ROUTER (Step -1 du pipeline) — court-circuite le RAG
            # pour les meta-questions (capabilities, sources, scope, internals,
            # greeting). Évite : (a) hallucination sur questions méta,
            # (b) leakage de l'architecture vers l'utilisateur, (c) coût RAG
            # inutile pour les salutations / questions hors-scope.
            # En cours de conversation, une relance est presque toujours la
            # suite de l'échange juridique : le classifieur LLM la jugerait
            # SANS l'historique (« Et pour les cadres ? » n'a aucun sens seul).
            # On garde les préfiltres déterministes (sécurité IP, salutations)
            # mais on saute le classifieur dès qu'il y a un historique.
            intent_result = await classify_intent(
                query=data.message,
                db=db,
                llm=agent.llm,
                organisation_id=conversation.organisation_id,
                use_llm_fallback=not history,
            )
            if intent_result.static_answer is not None:
                logger.info(
                    "[INTENT] %s via %s — court-circuit RAG",
                    intent_result.intent.value, intent_result.via,
                )
                # Persist d'abord pour récupérer les ids — le frontend attend
                # {message_id, answer_id} dans chat_done pour reconstituer la
                # conversation côté UI. Émettre vide casse l'écran de chat.
                meta_user = await service.add_message(
                    conversation_id=conversation_id,
                    role="user",
                    content=data.message,
                )
                meta_assistant = await service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=intent_result.static_answer,
                )
                try:
                    meta_assistant.latency_ms = int((time.perf_counter() - t_total) * 1000)
                    # Pas d'incrément de quota pour les meta : elles ne
                    # consomment pas le RAG, cohérent côté facturation.
                    await db.commit()
                except Exception:
                    logger.exception("Failed to persist meta-answer message %s", meta_assistant.id)
                if conversation.title is None:
                    title = data.message[:100].strip()
                    if len(data.message) > 100:
                        title = title.rsplit(" ", 1)[0] + "…"
                    await service.update_title(conversation_id, title)
                yield _sse_event("chat_delta", {"content": intent_result.static_answer})
                yield _sse_event("chat_done", {
                    "message_id": str(meta_user.id),
                    "answer_id": str(meta_assistant.id),
                })
                return

            # 2b. Load org's CCN IDCC list for search filtering
            # Si l'organisation n'est pas soumise à une CCN, on n'en cherche pas.
            if org_context and org_context.get("not_subject_to_ccn"):
                org_idcc_list = None
            else:
                from app.models.ccn import OrganisationConvention
                idcc_result = await db.execute(
                    select(OrganisationConvention.idcc).where(
                        OrganisationConvention.organisation_id == conversation.organisation_id,
                        OrganisationConvention.use_custom.is_(False),
                    )
                )
                org_idcc_list = [r[0] for r in idcc_result.all()] or None

            # 2b. Send status: analyzing
            yield _sse_event("chat_status", {"step": "Analyse de votre question..."})

            # 3. Prepare context (steps 0-5: condensation, reformulation, search, rerank)
            # Generate a per-question UUID used as cost-tracker context_id, so
            # api_usage_logs are attributable to a single question (and not to
            # the whole conversation as before). The agent's `conversation_id`
            # parameter is in fact used as the cost context id.
            question_id = uuid.uuid4()
            results, reformulated, rag_trace = await agent.prepare_context(
                query=data.message,
                organisation_id=str(conversation.organisation_id),
                org_context=org_context,
                history=history if history else None,
                cited_sources=cited_sources if cited_sources else None,
                org_idcc_list=org_idcc_list,
                user_id=str(user.id),
                conversation_id=str(question_id),
            )

            # --- Hors-scope: send refusal as a normal answer, save to history ---
            if reformulated == _OUT_OF_SCOPE_MARKER:
                logger.info("[SCOPE] Hors-scope — returning refusal for: %s", data.message[:100])
                # Persist d'abord pour récupérer les ids (le frontend les
                # attend dans chat_done — émettre vide casse l'écran).
                oos_user = await service.add_message(
                    conversation_id=conversation_id,
                    role="user",
                    content=data.message,
                )
                oos_assistant = await service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=_OUT_OF_SCOPE_ANSWER,
                )
                yield _sse_event("chat_delta", {"content": _OUT_OF_SCOPE_ANSWER})
                yield _sse_event("chat_done", {
                    "message_id": str(oos_user.id),
                    "answer_id": str(oos_assistant.id),
                })
                # Persist minimal trace for the Quality page
                try:
                    oos_assistant.rag_trace = rag_trace.to_dict()
                    oos_assistant.latency_ms = int((time.perf_counter() - t_total) * 1000)
                    oos_assistant.question_id = question_id
                    await billing.increment_question_count(account)
                    await db.commit()
                except Exception:
                    logger.exception(
                        "[QUALITY] Failed to persist out-of-scope trace for message %s",
                        oos_assistant.id,
                    )
                if conversation.title is None:
                    title = data.message[:100].strip()
                    if len(data.message) > 100:
                        title = title.rsplit(" ", 1)[0] + "…"
                    await service.update_title(conversation_id, title)
                return

            if not results:
                yield _sse_event("chat_error", {
                    "error": "no_results",
                    "message": (
                        "Je n'ai pas trouvé de documents pertinents dans "
                        "votre base documentaire pour répondre à cette question."
                    ),
                })
                return

            # 3. Send status: searching done, preparing response
            yield _sse_event("chat_status", {"step": "Recherche dans les sources..."})

            # 3b. Send sources before generation starts
            sources = agent.format_sources(results)
            sources_dicts = [dataclasses.asdict(s) for s in sources]
            yield _sse_event("chat_sources", {"sources": sources_dicts})
            t_sources = time.perf_counter()
            logger.info(
                "[PERF] Sources sent to client %.0fms after request",
                (t_sources - t_total) * 1000,
            )

            # 4. Stream LLM generation
            yield _sse_event("chat_status", {"step": "Rédaction de la réponse..."})

            if await request.is_disconnected():
                return

            full_answer = ""
            try:
                async for chunk in agent.stream_generate(
                    data.message, results,
                    org_context=org_context,
                    history=history,
                    low_confidence=rag_trace.low_confidence,
                    condensed_query=reformulated,
                ):
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

            # Finalize trace : add stream perf + compute total latency
            rag_trace.perf_ms["generate"] = (t_stream_done - t_sources) * 1000
            total_latency_ms = int((t_stream_done - t_total) * 1000)
            rag_trace.perf_ms["total"] = float(total_latency_ms)

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

            # 5b. Persist trace + question_id + latency on the assistant message.
            # The cost is NOT snapshot anymore — it is computed live via JOIN
            # on api_usage_logs.context_id = question_id, so /admin/quality
            # and /admin/costs always agree. Best-effort: a failure here must
            # NOT break the user response.
            try:
                assistant_message.rag_trace = rag_trace.to_dict()
                assistant_message.question_id = question_id
                assistant_message.latency_ms = total_latency_ms
                await billing.increment_question_count(account)
                await db.commit()
            except Exception:
                logger.exception(
                    "[QUALITY] Failed to persist rag_trace for message %s",
                    assistant_message.id,
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
            # Generic user-facing message — never expose internal service names
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
