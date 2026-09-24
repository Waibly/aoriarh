import asyncio
import base64
import dataclasses
import json
import logging
import time
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from openai import APITimeoutError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.limiter import limiter
from app.models.conversation import Message
from app.models.document import Document
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import (
    _SOURCE_TYPE_LABELS,
    RAGAgent,
)
from app.rag.config import (
    RAG_SLOW_NOTICE,
    RAG_TIMEOUT_STREAM_IDLE,
)
from app.rag.intent_router import classify_intent, is_security_response
from app.rag.pipeline import prepare_rag_context
from app.rag.search_feedback import search_feedback
from app.schemas.conversation import (
    ChatRequest,
    ConversationCreate,
    ConversationRead,
    ConversationReadWithMessages,
    LinkedInPostResponse,
    MessageFeedback,
    MessageRead,
    SocialMediaGenerationResponse,
    SocialMediaImageResponse,
    SocialMediaRenderRequest,
    SocialMediaRenderResponse,
    XPostRequest,
    XPostResponse,
)
from app.services.billing_service import BillingService
from app.services.conversation_service import ConversationService
from app.services.security_alert_service import send_security_alert_bg

logger = logging.getLogger(__name__)

router = APIRouter()


class ExistingDocumentAttachment(BaseModel):
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/{conversation_id}/document-library")
@limiter.limit("120/minute")
async def search_conversation_library(
    conversation_id: uuid.UUID, request: Request, response: Response,
    name: str = Query("", max_length=200),
    uploaded_from: date | None = None, uploaded_to: date | None = None,
    offset: int = Query(0, ge=0, le=10_000), limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.conversation_library_service import ConversationLibraryService

    service = ConversationLibraryService(db)
    conversation = await service.conversation(conversation_id, user)
    response.headers["Cache-Control"] = "private, no-store"
    return await service.search(conversation, name=name, uploaded_from=uploaded_from,
                                uploaded_to=uploaded_to, offset=offset, limit=limit)


@router.post("/{conversation_id}/document-library/{document_id}")
@limiter.limit("30/hour")
async def prepare_existing_conversation_document(
    conversation_id: uuid.UUID, document_id: uuid.UUID,
    data: ExistingDocumentAttachment, request: Request, response: Response,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.services.conversation_library_service import ConversationLibraryService

    service = ConversationLibraryService(db)
    conversation = await service.conversation(conversation_id, user)
    billing = BillingService(db)
    account = await billing.get_account_for_organisation(conversation.organisation_id)
    billing.ensure_plan_active(account)
    response.headers["Cache-Control"] = "private, no-store"
    return await service.prepare(conversation, user, document_id, data.source_sha256)


@router.post("/{conversation_id}/documents", status_code=201)
@limiter.limit("30/hour")
async def attach_conversation_document(
    conversation_id: uuid.UUID, request: Request, file: UploadFile,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    from app.core.config import settings
    from app.rag.tasks import enqueue_ingestion
    from app.rag.text_extractor import TextExtractor
    from app.services.document_extraction_service import DocumentExtractionService, SourceSnapshot
    from app.services.document_service import DocumentService, storage

    conversation = await ConversationService(db).get_conversation(conversation_id, user)
    from app.core.dependencies import verify_org_membership
    if user.role != "admin" and (
        await verify_org_membership(conversation.organisation_id, user, db) is None
    ):
        raise HTTPException(403, "Vous n'avez plus accès à cette organisation")
    if not settings.document_extraction_enabled_for(conversation.organisation_id):
        raise HTTPException(409, "Les pièces jointes ne sont pas activées pour cette organisation")
    billing = BillingService(db)
    account = await billing.get_account_for_organisation(conversation.organisation_id)
    billing.ensure_plan_active(account)
    org = await db.get(Organisation, conversation.organisation_id)
    await billing.check_document_limit(org)
    doc = await DocumentService(db).upload_document(file, "divers", org.id, user.id,
                                                   max_file_size=2 * 1024 * 1024)
    # The company original remains available even if extraction/queue fails.
    extraction = DocumentExtractionService(db, storage)
    try:
        raw_bytes = await asyncio.to_thread(storage.get_file_bytes, doc.storage_path)
        await extraction.extract(SourceSnapshot.from_document(doc), raw_bytes, TextExtractor())
        manifest = await extraction.status(doc.id, org.id, user.id)
        await enqueue_ingestion(str(doc.id), expected_source=doc.storage_path)
    except Exception:
        raise HTTPException(
            503,
            "Fichier enregistré dans Documents, mais préparation incomplète ; "
            "aucune pièce jointe confirmée",
        ) from None
    from app.services.conversation_document_service import attachment_readiness

    manifest = await extraction.reference_status(
        doc.id, org.id, user.id, manifest["extraction_id"]
    )
    return {"document_id": str(doc.id), "extraction_id": str(manifest["extraction_id"]),
            "name": doc.name, "coverage": manifest["coverage"],
            "text_bytes": manifest["text_bytes"], **attachment_readiness(manifest)}


@router.get("/{conversation_id}/documents/{document_id}/readiness")
@limiter.limit("120/minute")
async def conversation_document_readiness(
    conversation_id: uuid.UUID,
    document_id: uuid.UUID,
    extraction_id: uuid.UUID,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.conversation_document_service import attachment_readiness
    from app.services.document_extraction_service import DocumentExtractionService

    conversation = await ConversationService(db).get_conversation(conversation_id, user)
    manifest = await DocumentExtractionService(db).reference_status(
        document_id, conversation.organisation_id, user.id, extraction_id
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "document_id": str(document_id),
        "extraction_id": str(extraction_id),
        "name": manifest["source_name"],
        "text_bytes": manifest["text_bytes"],
        **attachment_readiness(manifest),
    }


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
    doc = (
        await db.execute(select(Document).where(Document.id == document_id))
    ).scalar_one_or_none()

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
                f"Format '{fmt}' non affichable inline. Utilisez le téléchargement du document."
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
    un appel LLM dédié, persiste la fiche (page « Mes fiches »), puis rend un PDF
    à la charte AORIA RH. Renvoie 422 si la réponse ne se prête pas à une fiche
    générale (cas particulier).
    """
    import dataclasses as _dc
    from datetime import datetime

    from app.models.fiche import Fiche
    from app.services.fiche_service import (
        fiche_filename,
        generate_fiche_content,
        render_fiche_pdf,
        select_fiche_references,
    )

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()

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

    # Contrôle serveur avant tout appel LLM : masquer le bouton dans le front
    # ne suffit pas, l'endpoint doit rester sûr s'il est appelé directement.
    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas être transformée en fiche pratique.",
        )

    # Retrouve la question (dernier message utilisateur avant cette réponse).
    question = ""
    for m in conversation.messages:
        if m.created_at >= message.created_at:
            break
        if m.role == "user":
            question = m.content

    org = (
        await db.execute(
            select(Organisation.name).where(Organisation.id == conversation.organisation_id)
        )
    ).scalar_one_or_none()

    sources = message.sources if isinstance(message.sources, list) else []
    available_references = select_fiche_references(message.content, sources)

    try:
        gen = await generate_fiche_content(
            question=question,
            answer_markdown=message.content,
            sources=available_references,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
        )
    except Exception:
        logger.exception("Échec de génération de fiche pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La génération de la fiche a échoué. Veuillez réessayer.",
        )

    if not gen.eligible or gen.content is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=gen.reason or "Cette réponse ne se prête pas à une fiche pratique.",
        )

    # Les métadonnées de référence suivent désormais le corps final, pas la
    # réponse conversationnelle plus longue dont il est issu.
    references = select_fiche_references(gen.content.body_html, sources)

    # Persiste (ou met à jour) la fiche : une seule par message source, pour
    # éviter les doublons quand l'utilisateur reclique sur le bouton.
    content_dict = _dc.asdict(gen.content)
    existing = (
        await db.execute(
            select(Fiche).where(
                Fiche.user_id == user.id,
                Fiche.message_id == message.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.title = gen.content.titre[:200]
        existing.content = content_dict
        existing.sources = references
    else:
        db.add(
            Fiche(
                organisation_id=conversation.organisation_id,
                user_id=user.id,
                message_id=message.id,
                title=gen.content.titre[:200],
                content=content_dict,
                sources=references,
            )
        )
    await db.commit()

    generated_at = datetime.now()
    pdf_bytes = render_fiche_pdf(
        gen.content,
        references,
        generated_at=generated_at,
        org_name=org,
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fiche_filename(gen.content)}"',
        },
    )


@router.post(
    "/messages/{message_id}/linkedin-post",
    response_model=LinkedInPostResponse,
)
@limiter.limit("10/minute")
async def generate_message_linkedin_post(
    message_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> LinkedInPostResponse:
    """Génère un brouillon LinkedIn autonome depuis une réponse du chat.

    Le message, la conversation et les fiches ne sont jamais modifiés. La
    sortie non vide du LLM est renvoyée telle quelle, accompagnée seulement de
    métadonnées et d'éventuels avertissements non bloquants.
    """
    from app.services.linkedin_post_service import generate_linkedin_post

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )

    # Cette fonctionnalité éditoriale ne doit pas transformer une conversation
    # client consultable par un admin depuis les outils de contrôle qualité.
    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le post LinkedIn ne peut être généré que depuis votre propre conversation.",
        )

    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut devenir un post LinkedIn.",
        )

    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas devenir un post LinkedIn.",
        )

    question = ""
    for conversation_message in conversation.messages:
        if conversation_message.created_at >= message.created_at:
            break
        if conversation_message.role == "user":
            question = conversation_message.content

    sources = message.sources if isinstance(message.sources, list) else []
    try:
        generation = await generate_linkedin_post(
            question=question,
            answer_markdown=message.content,
            sources=sources,
            user_profile=user.profil_metier,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
            message_id=str(message.id),
        )
    except Exception:
        logger.exception("Échec de génération LinkedIn pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La génération du post LinkedIn a échoué. Veuillez réessayer.",
        )

    return LinkedInPostResponse(
        content=generation.content,
        character_count=len(generation.content),
        references=generation.references,
        warnings=generation.warnings,
    )


@router.post(
    "/messages/{message_id}/x-post",
    response_model=XPostResponse,
)
@limiter.limit("10/minute")
async def generate_message_x_post(
    message_id: uuid.UUID,
    data: XPostRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> XPostResponse:
    """Génère un post X court ou un fil compatible avec un compte gratuit."""

    from app.services.social_media_service import generate_x_visual
    from app.services.x_post_service import generate_x_post

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )
    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le post X ne peut être généré que depuis votre propre conversation.",
        )
    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut devenir un post X.",
        )
    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas devenir un post X.",
        )

    question = ""
    for conversation_message in conversation.messages:
        if conversation_message.created_at >= message.created_at:
            break
        if conversation_message.role == "user":
            question = conversation_message.content

    sources = message.sources if isinstance(message.sources, list) else []
    try:
        generation = await generate_x_post(
            question=question,
            answer_markdown=message.content,
            sources=sources,
            format=data.format,
            user_profile=user.profil_metier,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
            message_id=str(message.id),
        )
    except Exception:
        logger.exception("Échec de génération X pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La génération du post X a échoué. Veuillez réessayer.",
        )

    visual = None
    visual_error = None
    try:
        visual = await generate_x_visual(
            question=question,
            answer_markdown=message.content,
            sources=sources,
            user_profile=user.profil_metier,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
            message_id=str(message.id),
        )
    except Exception:
        logger.exception("Échec de génération du visuel X pour %s", message_id)
        visual_error = (
            "Le texte X a bien été généré, mais la génération du visuel a échoué. "
            "Le texte reste disponible sans modification."
        )

    return XPostResponse(
        content=generation.content,
        character_count=len(generation.content),
        posts=generation.posts,
        format=generation.format,
        references=generation.references,
        warnings=generation.warnings,
        visual_raw_content=visual.raw_content if visual is not None else None,
        visual_html=visual.html if visual is not None else None,
        visual_warnings=visual.warnings if visual is not None else [],
        visual_error=visual_error,
    )


def _encode_social_media_images(images: list) -> list[SocialMediaImageResponse]:
    return [
        SocialMediaImageResponse(
            filename=image.filename,
            content_base64=base64.b64encode(image.content).decode("ascii"),
        )
        for image in images
    ]


@router.post(
    "/messages/{message_id}/social-media",
    response_model=SocialMediaGenerationResponse,
)
@limiter.limit("5/minute")
async def generate_message_social_media(
    message_id: uuid.UUID,
    request: Request,
    include_post: bool = False,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> SocialMediaGenerationResponse:
    """Génère un média seul ou un post LinkedIn avec son carrousel.

    Toute sortie LLM non vide est renvoyée telle quelle, même si un contrôle
    informatif signale un problème. Aucun fallback éditorial ni post-traitement
    correctif n'est appliqué. Les images ne sont rendues qu'à l'export.
    """

    from app.services.linkedin_post_service import generate_linkedin_carousel_post
    from app.services.social_media_service import generate_social_media

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )
    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le média ne peut être généré que depuis votre propre conversation.",
        )
    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut devenir un média.",
        )
    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas devenir un média.",
        )

    question = ""
    for conversation_message in conversation.messages:
        if conversation_message.created_at >= message.created_at:
            break
        if conversation_message.role == "user":
            question = conversation_message.content

    sources = message.sources if isinstance(message.sources, list) else []
    try:
        generation = await generate_social_media(
            question=question,
            answer_markdown=message.content,
            sources=sources,
            user_profile=user.profil_metier,
            organisation_id=str(conversation.organisation_id),
            user_id=str(user.id),
            message_id=str(message.id),
            linkedin_carousel=include_post,
        )
    except Exception:
        logger.exception("Échec de génération du média pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La génération du média a échoué. Veuillez réessayer.",
        )

    post = None
    post_error = None
    if include_post:
        try:
            post = await generate_linkedin_carousel_post(
                question=question,
                answer_markdown=message.content,
                sources=sources,
                carousel_content=generation.raw_content,
                user_profile=user.profil_metier,
                organisation_id=str(conversation.organisation_id),
                user_id=str(user.id),
                message_id=str(message.id),
            )
        except Exception:
            logger.exception(
                "Échec de génération du post carrousel pour %s", message_id
            )
            post_error = (
                "Le carrousel a bien été généré, mais son post d'accompagnement a "
                "échoué. La sortie du carrousel reste disponible sans modification."
            )

    return SocialMediaGenerationResponse(
        post=(
            LinkedInPostResponse(
                content=post.content,
                character_count=len(post.content),
                references=post.references,
                warnings=post.warnings,
            )
            if post is not None
            else None
        ),
        post_error=post_error,
        raw_content=generation.raw_content,
        html=generation.html,
        images=[],
        references=generation.references,
        warnings=generation.warnings,
        render_error=None,
    )


@router.post(
    "/messages/{message_id}/social-media/render",
    response_model=SocialMediaRenderResponse,
)
@limiter.limit("10/minute")
async def render_message_social_media(
    message_id: uuid.UUID,
    data: SocialMediaRenderRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> SocialMediaRenderResponse:
    """Convertit strictement le HTML édité par l'admin en images PNG."""

    from starlette.concurrency import run_in_threadpool

    from app.services.social_media_service import render_social_media_pngs

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )
    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le média ne peut être rendu que depuis votre propre conversation.",
        )
    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut devenir un média.",
        )
    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas devenir un média.",
        )

    try:
        images = await run_in_threadpool(render_social_media_pngs, data.html)
    except Exception:
        logger.exception("Échec du rendu du HTML édité pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Le HTML n'a pas pu être rendu en PNG. Il reste disponible sans "
                "modification dans l'éditeur."
            ),
        )

    return SocialMediaRenderResponse(images=_encode_social_media_images(images))


@router.post("/messages/{message_id}/social-media/pdf")
@limiter.limit("10/minute")
async def download_message_social_media_pdf(
    message_id: uuid.UUID,
    data: SocialMediaRenderRequest,
    request: Request,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Convertit strictement le HTML édité par l'admin en PDF LinkedIn."""

    from starlette.concurrency import run_in_threadpool

    from app.services.social_media_service import render_social_media_pdf

    message = (
        await db.execute(select(Message).where(Message.id == message_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message non trouvé",
        )

    service = ConversationService(db)
    conversation = await service.get_conversation(
        conversation_id=message.conversation_id,
        user=user,
    )
    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Le média ne peut être exporté que depuis votre propre conversation.",
        )
    if message.role != "assistant" or not (message.content or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seule une réponse de l'assistant peut devenir un média.",
        )
    if is_security_response(message.content, message.rag_trace):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réponse de sécurité ne peut pas devenir un média.",
        )

    try:
        pdf = await run_in_threadpool(render_social_media_pdf, data.html)
    except Exception:
        logger.exception("Échec de l'export PDF du média pour le message %s", message_id)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Le HTML n'a pas pu être rendu en PDF. Il reste disponible sans "
                "modification dans l'éditeur."
            ),
        )

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="aoria-media-linkedin.pdf"'
        },
    )


async def _load_org_context(
    db: AsyncSession, organisation_id: uuid.UUID
) -> dict[str, str | bool | None] | None:
    """Load organisation profile for RAG context injection."""
    from app.services.organisation_context_service import load_organisation_context

    return await load_organisation_context(db, organisation_id)


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _finalize_case_answer(db, conversation_id, message_id, answer_id, prepared):
    """A dossier persistence failure must not discard an already saved answer."""
    from app.services.case_file_service import CaseFileService
    try:
        version = await CaseFileService(db).link_task_answer(
            conversation_id, uuid.UUID(message_id), uuid.UUID(answer_id),
            expected_version=(prepared.trace.case_file_observation or {}).get("case_file_version"),
            used_version=(prepared.case_context or {}).get("dossier", {}).get("version"),
        )
        return version, False
    except Exception:
        await db.rollback()
        logger.exception("Case-file finalization failed; original answer remains saved")
        prepared.trace.search_plan = {
            **(prepared.trace.search_plan or {}), "case_finalization_error": True,
        }
        return None, True


_SLOW_GENERATION_NOTICE = "La rédaction prend plus de temps que d'habitude, désolé pour l'attente…"
_SLOW_CONTEXT_NOTICE = "L'analyse prend plus de temps que d'habitude, merci de patienter…"


async def _stream_with_idle_guard(agen, idle_timeout: float, slow_notice: float):
    """Itère un flux de génération en surveillant sa PROGRESSION, jamais sa durée.

    Principe : ne jamais couper une réponse qui avance, même lentement.
    Émet des tuples :
    - ("chunk", str)  : un morceau de réponse ;
    - ("slow", None)  : rien reçu depuis `slow_notice` s — informer l'utilisateur
      que c'est plus long que d'habitude (émis au plus une fois) ;
    - ("dead", None)  : rien reçu depuis `idle_timeout` s — le flux est
      considéré mort, l'appelant conserve le déjà-émis.
    """
    aiter = agen.__aiter__()
    notice_sent = False
    # Après le signal « slow », on n'attend que le RESTE du délai d'inactivité
    # (le silence total avant abandon reste égal à idle_timeout).
    remainder = max(idle_timeout - slow_notice, 0.05)
    task: asyncio.Task | None = None
    try:
        while True:
            if task is None:
                task = asyncio.ensure_future(anext(aiter))
            try:
                # shield : le timeout ne doit pas annuler l'attente du token —
                # on veut pouvoir continuer à l'attendre après l'avoir signalé.
                if notice_sent:
                    chunk = await asyncio.wait_for(
                        asyncio.shield(task),
                        idle_timeout,
                    )
                else:
                    try:
                        chunk = await asyncio.wait_for(
                            asyncio.shield(task),
                            slow_notice,
                        )
                    except TimeoutError:
                        notice_sent = True
                        yield ("slow", None)
                        chunk = await asyncio.wait_for(
                            asyncio.shield(task),
                            remainder,
                        )
            except TimeoutError:
                yield ("dead", None)
                return
            except StopAsyncIteration:
                return
            task = None
            yield ("chunk", chunk)
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # CancelledError inclus
                pass
        try:
            await agen.aclose()
        except Exception:
            pass


def _source_key(src: dict) -> tuple:
    """Clé d'identité d'une source pour la déduplication (Couche 2).

    Une même source peut apparaître dans un tour précédent (source portée) ET
    dans les résultats frais du tour courant : on l'écarte alors du bloc porté."""
    return (
        src.get("document_id"),
        tuple(sorted(src.get("article_nums") or [])),
        src.get("numero_pourvoi"),
    )


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
    search_details: dict | None = None
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
    results, reformulated, rag_trace = await prepare_rag_context(
        agent,
        query=data.query,
        organisation_id=str(data.organisation_id),
        org_context=org_context,
        history=None,
        cited_sources=None,
        org_idcc_list=org_idcc_list,
        user_id=str(user.id),
        context_id=str(question_id),
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
        search_details=search_feedback(rag_trace),
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

    from app.services.conversation_document_service import (
        active_references,
        read_conversation_documents,
    )
    references = active_references(conversation.messages, data.document_references)
    initial_reference_ids = {str(reference["document_id"]) for reference in references}
    documents, document_continuity = await read_conversation_documents(
        db, conversation, user, references, query=data.message,
    )
    if documents:
        references = [{"document_id": str(d["document_id"]),
                       "extraction_id": str(d["extraction_id"]), "name": d["source_name"]}
                      for d in documents]

    # Persist the user's exact request before any intent/planning/generation
    # call. It becomes the stable provenance for dossier facts and tasks, and
    # remains available when a later technical step fails.
    user_message = await service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
        document_references=references,
    )

    # 2. Load org context for RAG
    org_context = await _load_org_context(db, conversation.organisation_id)
    if org_context is not None:
        org_context["profil_metier"] = user.profil_metier

    async def sse_generator():  # noqa: C901
        nonlocal documents, references
        t_total = time.perf_counter()
        agent = RAGAgent()
        recent_messages = conversation.messages[-6:]
        history = [{"role": m.role, "content": m.content} for m in recent_messages]
        # Extract source names from recent assistant messages for condensation
        cited_sources: list[str] = []
        for m in recent_messages:
            if m.role == "assistant" and m.sources:
                for src in m.sources:
                    name = src.get("document_name") if isinstance(src, dict) else None
                    if name and name not in cited_sources:
                        cited_sources.append(name)
        # Couche 2 — sources portées : le TEXTE des sources des 2 derniers tours
        # assistant, relu depuis les messages persistés (jamais re-cherché), pour
        # que le modèle puisse enchaîner sur ce qu'il vient de citer. Les messages
        # proviennent de `conversation` (déjà filtrée par organisation via
        # get_conversation) → même organisation_id par construction, pas de
        # cross-tenant. Déduplication vs sources fraîches faite plus bas.
        carried_raw: list[dict] = []
        _carried_seen: set = set()
        _assistant_turns = 0
        for m in reversed(recent_messages):
            if m.role != "assistant" or not m.sources:
                continue
            _assistant_turns += 1
            if _assistant_turns > 2:
                break
            for src in m.sources:
                if not isinstance(src, dict):
                    continue
                key = _source_key(src)
                if key in _carried_seen:
                    continue
                _carried_seen.add(key)
                carried_raw.append(src)
        try:
            # 2a. INTENT ROUTER (Step -1 du pipeline) — court-circuite le RAG
            # pour les meta-questions (capabilities, sources, scope, internals,
            # greeting). Évite : (a) hallucination sur questions méta,
            # (b) leakage de l'architecture vers l'utilisateur, (c) coût RAG
            # inutile pour les salutations / questions hors-scope.
            # Les contrôles déterministes de sécurité et les réponses méta
            # restent ici. La décision métier appartient au planificateur
            # général plus bas : aucun second classifieur LLM en amont.
            intent_result = await classify_intent(
                query=data.message,
                db=db,
                llm=agent.llm,
                organisation_id=conversation.organisation_id,
                use_llm_fallback=False,
            )
            if intent_result.raw_response:
                yield _sse_event("chat_search_details", search_feedback({
                    "router_raw_response": intent_result.raw_response,
                }))
            if intent_result.static_answer is not None and (
                not documents or is_security_response(intent_result.static_answer)
            ):
                logger.info(
                    "[INTENT] %s via %s — court-circuit RAG",
                    intent_result.intent.value,
                    intent_result.via,
                )
                # Persist d'abord pour récupérer les ids — le frontend attend
                # {message_id, answer_id} dans chat_done pour reconstituer la
                # conversation côté UI. Émettre vide casse l'écran de chat.
                meta_assistant = await service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=intent_result.static_answer,
                )
                try:
                    meta_assistant.rag_trace = {
                        "static_intent": intent_result.intent.value,
                        "router_raw_response": intent_result.raw_response,
                        "security_event": intent_result.security_event,
                    }
                    meta_assistant.latency_ms = int((time.perf_counter() - t_total) * 1000)
                    # Pas d'incrément de quota pour les meta : elles ne
                    # consomment pas le RAG, cohérent côté facturation.
                    await db.commit()
                except Exception:
                    logger.exception("Failed to persist meta-answer message %s", meta_assistant.id)
                if intent_result.security_event is not None:
                    # Best-effort et hors chemin critique : Redis déduplique,
                    # Brevo ne peut ni ralentir ni casser la réponse utilisateur.
                    send_security_alert_bg(
                        event_type=intent_result.security_event,
                        query=data.message,
                        user_id=str(user.id),
                        user_email=user.email,
                        user_name=user.full_name,
                        user_role=user.role,
                        organisation_id=str(conversation.organisation_id),
                        organisation_name=(org_context or {}).get("nom"),
                        conversation_id=str(conversation_id),
                        message_id=str(user_message.id),
                        detected_via=intent_result.via,
                    )
                if conversation.title is None:
                    title = data.message[:100].strip()
                    if len(data.message) > 100:
                        title = title.rsplit(" ", 1)[0] + "…"
                    await service.update_title(conversation_id, title)
                yield _sse_event("chat_delta", {"content": intent_result.static_answer})
                yield _sse_event(
                    "chat_done",
                    {
                        "message_id": str(user_message.id),
                        "answer_id": str(meta_assistant.id),
                        "fiche_eligible": intent_result.security_event is None,
                    },
                )
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
            yield _sse_event("chat_status", {"step": "Prise en compte de votre situation…"})

            # 3. Prepare context (steps 0-5: condensation, reformulation, search, rerank)
            # Generate a per-question UUID used as cost-tracker context_id, so
            # api_usage_logs are attributable to a single question (and not to
            # the whole conversation as before). The agent's `conversation_id`
            # parameter is in fact used as the cost context id.
            question_id = uuid.uuid4()
            async def legal_context(query=data.message, *, search_plan=None):
                # Each branch owns its mutable search plan, diagnostics and caches.
                branch_agent = RAGAgent()
                case_ccn_unknown = search_plan is not None and (
                    "organisation_convention_not_applicable_to_case" in search_plan.warnings
                )
                branch_org_context = org_context
                if case_ccn_unknown and org_context:
                    branch_org_context = {
                        key: value for key, value in org_context.items()
                        if key not in {"convention_collective", "not_subject_to_ccn"}
                    }
                return await prepare_rag_context(
                    branch_agent, query=query, organisation_id=str(conversation.organisation_id),
                    org_context=branch_org_context, history=history or None,
                    cited_sources=cited_sources or None,
                    org_idcc_list=None if case_ccn_unknown else org_idcc_list,
                    user_id=str(user.id), context_id=str(question_id),
                    **({"search_plan": search_plan} if search_plan is not None else {}),
                )
            from app.rag.config import EXPAND_MODEL
            from app.services.conversation_orchestrator import prepare_conversation_context

            agent._org_id = str(conversation.organisation_id)
            agent._user_id = str(user.id)
            agent._conversation_id = str(question_id)
            agent._is_replay = False
            progress_queue: asyncio.Queue[str] = asyncio.Queue()
            progress_task = None
            current_step = "Prise en compte de votre situation…"
            ctx_task = asyncio.ensure_future(
                prepare_conversation_context(
                    agent,
                    db=db,
                    conversation=conversation,
                    user=user,
                    query=data.message,
                    references=references,
                    documents=documents,
                    document_continuity=document_continuity,
                    history=history,
                    legal_search=legal_context,
                    model=EXPAND_MODEL,
                    org_context=org_context,
                    org_idcc_list=org_idcc_list,
                    cited_sources=cited_sources or None,
                    source_message_id=user_message.id,
                    parallel_legal_search=True,
                    on_progress=progress_queue.put_nowait,
                )
            )
            try:
                # Heartbeats keep the connection alive without imposing a
                # wall-clock deadline on a valid, potentially long operation.
                while not ctx_task.done():
                    if progress_task is None:
                        progress_task = asyncio.create_task(progress_queue.get())
                    done, _ = await asyncio.wait(
                        {ctx_task, progress_task}, timeout=RAG_SLOW_NOTICE,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if await request.is_disconnected():
                        return
                    if progress_task in done:
                        current_step = progress_task.result()
                        progress_task = None
                        yield _sse_event("chat_status", {"step": current_step})
                    if not done:
                        yield _sse_event("chat_status", {
                            "step": current_step, "notice": _SLOW_CONTEXT_NOTICE,
                        })
                prepared_context = await ctx_task
            except (TimeoutError, APITimeoutError):
                logger.warning(
                    "Context dependency timed out for conversation %s",
                    conversation_id,
                )
                yield _sse_event(
                    "chat_error",
                    {
                        "error": "timeout",
                        "message": (
                            "La connexion à un service nécessaire a expiré. "
                            "Veuillez réessayer dans quelques instants."
                        ),
                    },
                )
                return

            finally:
                if progress_task is not None:
                    progress_task.cancel()
                    await asyncio.gather(progress_task, return_exceptions=True)
                if not ctx_task.done():
                    ctx_task.cancel()
                    await asyncio.gather(ctx_task, return_exceptions=True)

            results = prepared_context.results
            reformulated = prepared_context.reformulated
            rag_trace = prepared_context.trace
            documents = prepared_context.documents
            references = prepared_context.references
            if (rag_trace.error != "case_execution_conflict"
                    and user_message.document_references != references):
                user_message.document_references = references
                await db.commit()

            if intent_result.raw_response:
                rag_trace.search_plan = {
                    **(rag_trace.search_plan or {}),
                    "intent_router_raw_response": intent_result.raw_response,
                }
            yield _sse_event("chat_search_details", search_feedback(rag_trace))
            if rag_trace.search_plan_validation.get("request_errors"):
                yield _sse_event("chat_warning", {
                    "message": "Certaines opérations ou mises à jour du dossier n’ont pas pu être "
                    "exécutées. Les opérations indépendantes ont été conservées ; les détails "
                    "et la sortie originale sont consultables dans le dossier.",
                })
            case_observation = rag_trace.case_file_observation or {}
            case_application = case_observation.get("application_result") or {}
            if rag_trace.error == "case_context_budget_exceeded":
                yield _sse_event("chat_error", {
                    "error": rag_trace.error,
                    "message": "Le contexte dépasse la limite de traitement. Archivez les éléments "
                    "devenus inutiles ou ouvrez une conversation plus ciblée. "
                    "Aucun texte n’a été tronqué.",
                })
                return
            if rag_trace.error == "case_execution_conflict":
                yield _sse_event("chat_error", {
                    "error": "case_execution_conflict",
                    "message": "Le dossier a changé ou son enregistrement a échoué. "
                    "Rechargez-le avant de relancer votre demande ; aucun calcul obsolète "
                    "n’a été utilisé.",
                })
                return
            if case_application.get("applied") is True:
                yield _sse_event(
                    "case_file_updated",
                    {
                        "conversation_id": str(conversation_id),
                        "case_file_id": case_observation.get("case_file_id"),
                        "version": case_application.get("version"),
                    },
                )
            if rag_trace.error in {"search_reranking_error", "search_context_error"}:
                yield _sse_event("chat_error", {
                    "error": rag_trace.error,
                    "message": (
                        "Le classement des documents a échoué. "
                        "Aucun classement de secours n’a été utilisé."
                        if rag_trace.error == "search_reranking_error"
                        else "Le contexte documentaire n’a pas pu être préparé. "
                        "Aucune réponse n’a été générée."
                    ),
                })
                return
            if rag_trace.error == "search_retrieval_error":
                yield _sse_event("chat_error", {
                    "error": "search_retrieval_error",
                    "message": (
                        "Une recherche documentaire a échoué. Aucune réponse n’a été "
                        "générée à partir des résultats incomplets."
                    ),
                })
                return
            if rag_trace.error == "search_planner_error":
                yield _sse_event("chat_error", {
                    "error": "search_planner_error",
                    "message": (
                        "Le plan de recherche n’a pas pu être exécuté. "
                        "Aucune recherche de secours n’a été lancée."
                    ),
                })
                return
            if prepared_context.direct_response is not None:
                direct_response = prepared_context.direct_response
                total_latency_ms = int((time.perf_counter() - t_total) * 1000)
                rag_trace.perf_ms["total"] = float(total_latency_ms)
                needs_title = conversation.title is None
                assistant_message = await service.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=direct_response,
                )
                user_message_id = str(user_message.id)
                assistant_message_id = str(assistant_message.id)
                if prepared_context.case_context is not None:
                    version, case_failed = await _finalize_case_answer(
                        db, conversation_id, user_message_id, assistant_message_id, prepared_context
                    )
                    if case_failed:
                        for instance in (assistant_message, conversation, account):
                            await db.refresh(instance)
                        yield _sse_event("chat_warning", {
                            "message": "La réponse est conservée, mais le dossier a changé ou sa "
                            "finalisation a échoué. Les tâches n’ont pas été clôturées.",
                        })
                    if version is not None:
                        yield _sse_event("case_file_updated", {
                            "conversation_id": str(conversation_id), "version": version,
                        })
                assistant_message.rag_trace = rag_trace.to_dict()
                assistant_message.question_id = question_id
                assistant_message.latency_ms = total_latency_ms
                await db.commit()
                try:
                    await billing.increment_question_count(account)
                    await db.commit()
                except Exception:
                    logger.exception(
                        "[BILLING] Failed to increment direct-response question count"
                    )
                    await db.rollback()
                if needs_title:
                    title = data.message[:100].strip()
                    if len(data.message) > 100:
                        title = title.rsplit(" ", 1)[0] + "…"
                    await service.update_title(conversation_id, title)
                yield _sse_event("chat_delta", {"content": direct_response})
                yield _sse_event(
                    "chat_done",
                    {
                        "message_id": user_message_id,
                        "answer_id": assistant_message_id,
                        "fiche_eligible": False,
                    },
                )
                return
            if not results and not prepared_context.generate_without_sources:
                yield _sse_event(
                    "chat_error",
                    {
                        "error": "no_results",
                        "message": (
                            "Je n'ai pas trouvé de documents pertinents dans "
                            "votre base documentaire pour répondre à cette question."
                        ),
                    },
                )
                return

            if documents:
                # Recheck current ACL/version after the potentially long legal search.
                from app.services.conversation_document_service import verify_conversation_documents

                await verify_conversation_documents(db, conversation, user, references)
                from app.rag.document_generation import build_document_task_context

                document_task_context = build_document_task_context(documents, results, rag_trace)

            # 3. Send status: searching done, preparing response
            if results:
                yield _sse_event("chat_status", {"step": "Préparation de la réponse…"})

            # 3b. Send sources before generation starts
            sources = agent.format_sources(results)
            sources_dicts = [dataclasses.asdict(s) for s in sources]
            for source in sources_dicts:
                for document in documents:
                    if source.get("document_id") == str(document["document_id"]):
                        source["extraction_id"] = str(document["extraction_id"])
                        source["coverage"] = document["coverage"]
                        source["selection_kind"] = (
                            "conversation_document_reference"
                            if str(document["document_id"]) in initial_reference_ids
                            else "natural_document_lookup"
                        )
            yield _sse_event("chat_sources", {"sources": sources_dicts})

            # Couche 2 — écarte des sources portées celles déjà présentes dans les
            # sources fraîches de ce tour (pas de doublon dans le prompt). Le
            # panneau UI reste = sources fraîches ; les portées ne nourrissent que
            # la génération.
            _fresh_keys = {_source_key(s) for s in sources_dicts}
            carried_sources = [s for s in carried_raw if _source_key(s) not in _fresh_keys]
            if documents:
                carried_sources = []  # No unchecked stale source copies in the documentary path.
            source_policy = rag_trace.search_plan or {}
            excluded_types = set(source_policy.get("excluded_source_types", []))
            exclusive_types = set(source_policy.get("exclusive_source_types", []))
            carried_sources = [s for s in carried_sources
                               if s.get("source_type") not in excluded_types
                               and (not exclusive_types or s.get("source_type") in exclusive_types)]
            if carried_sources:
                details = search_feedback(rag_trace)
                details["warnings"].append(
                    "Des passages de sources des tours précédents sont également transmis, "
                    "dans une limite de six sources et de 9 000 caractères par source. "
                    "Leur applicabilité à la nouvelle question n’est pas présumée."
                )
                yield _sse_event("chat_search_details", details)
                logger.info(
                    "[RAG] Couche 2 — %d source(s) portée(s) injectée(s) en génération",
                    len(carried_sources),
                )
            t_sources = time.perf_counter()
            logger.info(
                "[PERF] Sources sent to client %.0fms after request",
                (t_sources - t_total) * 1000,
            )

            # 4. Stream LLM generation
            yield _sse_event("chat_status", {"step": "Rédaction de la réponse…"})

            if await request.is_disconnected():
                return

            full_answer = ""
            generation_metrics = {}
            rag_trace.search_plan_usage["generation_metrics"] = generation_metrics
            stream_dead = False
            generation_interrupted = False
            try:
                # Garde d'inactivité : une réponse qui avance — même très
                # lentement — n'est JAMAIS coupée. Si rien n'arrive pendant
                # RAG_SLOW_NOTICE on affiche un message de patience ; si le
                # silence atteint RAG_TIMEOUT_STREAM_IDLE le flux est
                # considéré mort et le déjà-émis est conservé.
                async for kind, chunk in _stream_with_idle_guard(
                    agent.stream_generate(
                        data.message,
                        results,
                        org_context=org_context,
                        history=None if documents else history,
                        low_confidence=rag_trace.low_confidence,
                        condensed_query=reformulated,
                        carried_sources=carried_sources or None,
                        case_context=prepared_context.case_context,
                        generation_metrics=generation_metrics,
                        answer_format=(
                            rag_trace.search_plan.get("answer_format")
                            if rag_trace.search_plan
                            and rag_trace.search_plan_usage.get("execution") == "adaptive"
                            else None
                        ),
                        **({"document_continuity": document_continuity,
                            "document_task_context": document_task_context} if documents else {}),
                    ),
                    idle_timeout=RAG_TIMEOUT_STREAM_IDLE,
                    slow_notice=RAG_SLOW_NOTICE,
                ):
                    if await request.is_disconnected():
                        logger.info("Client disconnected during streaming")
                        return
                    if kind == "slow":
                        yield _sse_event(
                            "chat_status",
                            {"step": "Rédaction de la réponse…", "notice": _SLOW_GENERATION_NOTICE},
                        )
                        continue
                    if kind == "dead":
                        stream_dead = True
                        break
                    if chunk and not full_answer:
                        rag_trace.perf_ms["first_text"] = (time.perf_counter() - t_total) * 1000
                        rag_trace.perf_ms["generation_first_text"] = (
                            time.perf_counter() - t_sources
                        ) * 1000
                    full_answer += chunk
                    yield _sse_event("chat_delta", {"content": chunk})
            except Exception as stream_exc:
                generation_interrupted = True
                logger.warning(
                    "Stream generation interrupted after %d chars: %s",
                    len(full_answer),
                    stream_exc,
                )
                if not full_answer:
                    # Nothing generated — send error
                    yield _sse_event(
                        "chat_error",
                        {
                            "error": "server_error",
                            "message": (
                                "Une erreur est survenue lors de la génération "
                                "de la réponse. Veuillez réessayer."
                            ),
                        },
                    )
                    return
                # Partial content exists — continue to save what we have

            if stream_dead:
                logger.warning(
                    "[PERF] Stream silent for %.0fs — abandoned after %d chars",
                    RAG_TIMEOUT_STREAM_IDLE,
                    len(full_answer),
                )
                if not full_answer:
                    yield _sse_event(
                        "chat_error",
                        {
                            "error": "timeout",
                            "message": (
                                "La génération de la réponse n'a pas pu démarrer. "
                                "Veuillez réessayer dans quelques instants."
                            ),
                        },
                    )
                    return
                # The incident is separate from the verbatim generated answer.
                yield _sse_event("chat_warning", {
                    "error": "generation_interrupted",
                    "message": "La génération s’est interrompue. Le texte partiel est conservé.",
                })

            if not full_answer:
                yield _sse_event("chat_error", {
                    "error": "empty_generation", "message": "Le modèle a renvoyé une réponse vide.",
                })
                return
            if generation_interrupted and not stream_dead:
                yield _sse_event("chat_warning", {
                    "error": "generation_interrupted",
                    "message": "La génération s’est interrompue. Le texte partiel est conservé.",
                })
            t_stream_done = time.perf_counter()
            if stream_dead or generation_interrupted:
                rag_trace.search_plan = {
                    **(rag_trace.search_plan or {}), "generation_interrupted": True,
                }

            # Finalize trace : add stream perf + compute total latency
            rag_trace.perf_ms["generate"] = (t_stream_done - t_sources) * 1000
            total_latency_ms = int((t_stream_done - t_total) * 1000)
            rag_trace.perf_ms["total"] = float(total_latency_ms)

            # 5. Save the assistant message. The user message was persisted
            # before planning and already carries the final document links.
            assistant_message = await service.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_answer,
                sources=sources_dicts if sources_dicts else None,
            )
            # Ids capturés tout de suite : un rollback best-effort plus bas
            # expirerait les instances et l'accès à .id planterait chat_done.
            user_message_id = str(user_message.id)
            assistant_message_id = str(assistant_message.id)

            if (prepared_context.case_context is not None
                    and not stream_dead and not generation_interrupted):
                final_case_version, case_failed = await _finalize_case_answer(
                    db, conversation_id, user_message_id, assistant_message_id, prepared_context
                )
                if case_failed:
                    for instance in (assistant_message, conversation, account):
                        await db.refresh(instance)
                    yield _sse_event("chat_warning", {
                        "message": "La réponse est conservée, mais le dossier a changé ou sa "
                        "finalisation a échoué. Les tâches n’ont pas été clôturées.",
                    })
                if final_case_version is not None:
                    yield _sse_event("case_file_updated", {
                        "conversation_id": str(conversation_id),
                        "case_file_id": (rag_trace.case_file_observation or {}).get("case_file_id"),
                        "version": final_case_version,
                    })

            # 5b. Persist trace + question_id + latency on the assistant message.
            # The cost is NOT snapshot anymore — it is computed live via JOIN
            # on api_usage_logs.context_id = question_id, so /admin/quality
            # and /admin/costs always agree. Best-effort: a failure here must
            # NOT break the user response.
            # Trace et quota sont commités SÉPARÉMENT : un échec de la trace
            # (best-effort) ne doit pas faire sauter le décompte de la
            # question, ni l'inverse.
            # Capturé AVANT les commits/rollbacks best-effort : un rollback
            # expire les instances ORM et `conversation.title` deviendrait
            # inaccessible sans IO.
            needs_title = conversation.title is None
            trace_failed = False
            try:
                assistant_message.rag_trace = rag_trace.to_dict()
                assistant_message.question_id = question_id
                assistant_message.latency_ms = total_latency_ms
                await db.commit()
            except Exception:
                logger.exception(
                    "[QUALITY] Failed to persist rag_trace for message %s",
                    assistant_message_id,
                )
                await db.rollback()
                trace_failed = True
            try:
                if trace_failed:
                    # rollback() expire les instances ORM : recharger le
                    # compte avant de toucher à ses attributs.
                    await db.refresh(account)
                await billing.increment_question_count(account)
                await db.commit()
            except Exception:
                logger.exception(
                    "[BILLING] Failed to increment question count for account %s",
                    getattr(account, "id", "?"),
                )
                await db.rollback()

            # 6. Auto-generate title
            if needs_title:
                title = data.message[:100].strip()
                if len(data.message) > 100:
                    title = title.rsplit(" ", 1)[0] + "…"
                await service.update_title(conversation_id, title)

            t_db = time.perf_counter()
            logger.info(
                "[PERF] DB save %.0fms",
                (t_db - t_stream_done) * 1000,
            )

            # 7. Send done event with IDs
            yield _sse_event(
                "chat_done",
                {
                    "message_id": user_message_id,
                    "answer_id": assistant_message_id,
                    "fiche_eligible": True,
                },
            )

            logger.info(
                "[PERF] ══ TOTAL request %.0fms (context %.0fms + streaming %.0fms + db %.0fms)",
                (t_db - t_total) * 1000,
                (t_sources - t_total) * 1000,
                (t_stream_done - t_sources) * 1000,
                (t_db - t_stream_done) * 1000,
            )

        except Exception:
            logger.exception(
                "SSE streaming error for conversation %s",
                conversation_id,
            )
            # Generic user-facing message — never expose internal service names
            error_msg = (
                "Une erreur est survenue lors du traitement de votre question. Veuillez réessayer."
            )
            yield _sse_event(
                "chat_error",
                {
                    "error": "server_error",
                    "message": error_msg,
                },
            )

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
