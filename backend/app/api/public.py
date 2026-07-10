"""Endpoint public de démonstration — hero du site marketing → réponse dans l'app.

Un visiteur NON authentifié pose une question de droit social et obtient une
réponse sourcée, streamée, identique à celle du chat de l'app. Objectif :
prouver la valeur avant l'inscription (« réponse d'abord, compte ensuite »).

Différences avec le chat authentifié (`conversations.chat_stream`) :
  * Aucun JWT requis, aucun contrôle de quota/plan (pas d'Account).
  * Tourne sur une organisation « démo » technique SANS CCN installée : le
    filtre Qdrant existant (`search.py`) ne remonte donc QUE le corpus commun
    (Code du travail, jurisprudence, JORF…) — jamais les docs d'un client ni
    les conventions collectives. C'est le garde-fou de cloisonnement n°1.
  * Modèle de génération FORCÉ (`demo_llm_model`, gpt-5-mini) pour verrouiller
    le coût, indépendamment du modèle prod.

Trois garde-fous anti-abus / anti-coût :
  1. Cloudflare Turnstile (désactivé si `turnstile_secret` vide).
  2. Rate-limit par IP (slowapi).
  3. Plafond de dépense quotidien global (`demo_daily_budget_eur`), mesuré sur
     les coûts réels attribués à l'org démo dans `api_usage_logs`.
"""

import dataclasses
import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import _load_org_context, _sse_event
from app.core.config import settings
from app.core.database import async_session_factory, get_db
from app.core.limiter import limiter
from app.models.api_usage import ApiUsageLog
from app.models.conversation import Conversation
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import (
    RAGAgent,
    _OUT_OF_SCOPE_ANSWER,
    _OUT_OF_SCOPE_MARKER,
)
from app.rag.intent_router import classify_intent
from app.services.conversation_service import ConversationService

logger = logging.getLogger(__name__)

router = APIRouter()

# CTA affiché en fin de réponse pour pousser à l'inscription. Neutre côté
# contenu (pas de superlatif), cohérent avec le ton du site.
_DEMO_UPSELL = (
    "Cette réponse s'appuie sur le socle légal commun (Code du travail, "
    "jurisprudence). Pour une réponse calée sur **votre convention collective** "
    "et pour interroger vos propres accords, créez votre compte."
)

# Cache mémoire des ids démo (résolus une fois, seedés au démarrage).
_demo_ids: dict[str, uuid.UUID] = {}


class PublicAskRequest(BaseModel):
    message: str = Field(..., min_length=1)
    # Jeton Turnstile (ignoré si la vérification est désactivée côté serveur).
    turnstile_token: str | None = None
    # Permet les relances dans la même conversation démo (sinon nouvelle convo).
    conversation_id: uuid.UUID | None = None


async def _resolve_demo_ids(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Retourne (org_id, user_id) de la démo, seedés au démarrage (main.seed_demo).

    503 si absents : l'endpoint ne doit jamais improviser une org/user.
    """
    if "org" in _demo_ids and "user" in _demo_ids:
        return _demo_ids["org"], _demo_ids["user"]

    org_id = (await db.execute(
        select(Organisation.id).where(Organisation.name == settings.demo_org_name)
    )).scalar_one_or_none()
    user_id = (await db.execute(
        select(User.id).where(User.email == settings.demo_user_email)
    )).scalar_one_or_none()

    if org_id is None or user_id is None:
        logger.error("Démo non initialisée (org=%s user=%s)", org_id, user_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La démonstration est momentanément indisponible.",
        )

    _demo_ids["org"], _demo_ids["user"] = org_id, user_id
    return org_id, user_id


async def _demo_spend_today_usd(db: AsyncSession, demo_org_id: uuid.UUID) -> Decimal:
    """Somme des coûts (USD) attribués à l'org démo depuis minuit UTC.

    Tous les appels (expansion, embeddings, rerank, génération) sont loggés avec
    organisation_id = org démo, donc cette somme capture le coût total de la
    démo pour la journée.
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    total = (await db.execute(
        select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
            ApiUsageLog.organisation_id == demo_org_id,
            ApiUsageLog.created_at >= today_start,
        )
    )).scalar_one()
    return Decimal(str(total))


def _daily_budget_usd() -> Decimal:
    """Plafond quotidien converti d'EUR en USD (les coûts sont loggés en USD)."""
    rate = settings.usd_eur_rate or 0.92
    return Decimal(str(settings.demo_daily_budget_eur)) / Decimal(str(rate))


async def _verify_turnstile(token: str | None, remote_ip: str | None) -> bool:
    """Vérifie le jeton Cloudflare Turnstile. Désactivé si secret vide (dev)."""
    if not settings.turnstile_secret:
        return True
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.turnstile_secret,
                    "response": token,
                    **({"remoteip": remote_ip} if remote_ip else {}),
                },
            )
        return bool(resp.json().get("success", False))
    except Exception:
        logger.exception("Turnstile: échec de vérification — on refuse par défaut")
        return False


@router.post("/ask")
@limiter.limit("5/minute")
@limiter.limit("15/day")
async def public_ask(
    data: PublicAskRequest,
    request: Request,
) -> StreamingResponse:
    """Pose une question de démo (non authentifié) et streame la réponse (SSE)."""
    if not settings.demo_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Démo désactivée")

    # 1. Anti-bot : Turnstile
    remote_ip = get_remote_address(request)
    if not await _verify_turnstile(data.turnstile_token, remote_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vérification anti-robot échouée. Rechargez la page et réessayez.",
        )

    # 2. Bornes de longueur (anti-coût / anti-abus)
    message = (data.message or "").strip()
    if len(message) < settings.demo_min_question_chars:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Votre question est trop courte pour être traitée.",
        )
    if len(message) > settings.demo_max_question_chars:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Question limitée à {settings.demo_max_question_chars} caractères "
                "en démonstration. Créez un compte pour les questions longues."
            ),
        )

    # 3. Résolution démo + plafond budget quotidien
    async with async_session_factory() as pre_db:
        demo_org_id, demo_user_id = await _resolve_demo_ids(pre_db)
        spend = await _demo_spend_today_usd(pre_db, demo_org_id)
    if spend >= _daily_budget_usd():
        logger.warning("Démo: plafond quotidien atteint (%.4f USD)", spend)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "La démonstration a atteint sa limite pour aujourd'hui. "
                "Créez un compte pour poser vos questions sans attendre."
            ),
        )

    async def sse_generator():  # noqa: C901
        t_total = time.perf_counter()
        # Session dédiée au flux (le StreamingResponse survit à la requête).
        async with async_session_factory() as db:
            service = ConversationService(db)
            agent = RAGAgent()

            # 3a. Conversation démo : réutilise celle passée si elle appartient
            # bien à l'org démo (relances), sinon en crée une neuve.
            conversation = None
            if data.conversation_id is not None:
                conversation = (await db.execute(
                    select(Conversation).where(
                        Conversation.id == data.conversation_id,
                        Conversation.organisation_id == demo_org_id,
                    )
                )).scalar_one_or_none()
            if conversation is None:
                conversation = Conversation(
                    organisation_id=demo_org_id,
                    user_id=demo_user_id,
                    title=message[:100].strip() or None,
                )
                db.add(conversation)
                await db.commit()
                await db.refresh(conversation)

            # Contexte org démo (sans CCN → corpus commun uniquement). On retire
            # le NOM de l'org : sinon le prompt de génération écrit « chez <Nom> »
            # (ici « chez AORIA RH — Démo publique »), ce qui n'a pas de sens pour
            # un visiteur anonyme. Réponse générique attendue (« ici », « côté
            # employeur »), pas personnalisée à une entreprise.
            org_context = await _load_org_context(db, demo_org_id)
            if org_context is not None:
                org_context["nom"] = None

            try:
                yield _sse_event("chat_meta", {"conversation_id": str(conversation.id)})

                # 3b. Intent router : court-circuit RAG (salutations, méta).
                intent_result = await classify_intent(
                    query=message,
                    db=db,
                    llm=agent.llm,
                    organisation_id=demo_org_id,
                    use_llm_fallback=True,
                )
                if intent_result.static_answer is not None:
                    await service.add_message(
                        conversation_id=conversation.id, role="user", content=message,
                    )
                    await service.add_message(
                        conversation_id=conversation.id, role="assistant",
                        content=intent_result.static_answer,
                    )
                    yield _sse_event("chat_delta", {"content": intent_result.static_answer})
                    yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})
                    return

                yield _sse_event("chat_status", {"step": "Analyse de votre question..."})

                # 4. Préparation du contexte. org_idcc_list=None → corpus commun
                # strict (aucune CCN). question_id = contexte de coût.
                question_id = uuid.uuid4()
                results, reformulated, rag_trace = await agent.prepare_context(
                    query=message,
                    organisation_id=str(demo_org_id),
                    org_context=org_context,
                    history=None,
                    cited_sources=None,
                    org_idcc_list=None,
                    user_id=str(demo_user_id),
                    conversation_id=str(question_id),
                )

                if reformulated == _OUT_OF_SCOPE_MARKER:
                    await service.add_message(
                        conversation_id=conversation.id, role="user", content=message,
                    )
                    await service.add_message(
                        conversation_id=conversation.id, role="assistant",
                        content=_OUT_OF_SCOPE_ANSWER,
                    )
                    yield _sse_event("chat_delta", {"content": _OUT_OF_SCOPE_ANSWER})
                    yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})
                    return

                if not results:
                    yield _sse_event("chat_error", {
                        "error": "no_results",
                        "message": (
                            "Je n'ai pas trouvé de source pertinente dans le socle "
                            "légal commun pour cette question. Créez un compte et "
                            "importez votre convention collective pour aller plus loin."
                        ),
                    })
                    return

                # 5. Sources
                yield _sse_event("chat_status", {"step": "Recherche dans les sources..."})
                sources = agent.format_sources(results)
                sources_dicts = [dataclasses.asdict(s) for s in sources]
                yield _sse_event("chat_sources", {"sources": sources_dicts})

                # 6. Génération streamée — modèle FORCÉ gpt-5-mini.
                yield _sse_event("chat_status", {"step": "Rédaction de la réponse..."})
                if await request.is_disconnected():
                    return

                full_answer = ""
                try:
                    async for chunk in agent.stream_generate(
                        message, results,
                        # Pas de bloc « Entreprise de l'utilisateur » en démo :
                        # réponse générique, jamais « chez <une entreprise> ».
                        org_context=None,
                        history=None,
                        low_confidence=rag_trace.low_confidence,
                        condensed_query=reformulated,
                        model_override=settings.demo_llm_model,
                    ):
                        if await request.is_disconnected():
                            return
                        full_answer += chunk
                        yield _sse_event("chat_delta", {"content": chunk})
                except Exception as stream_exc:
                    logger.warning("Démo: streaming interrompu (%d car.): %s",
                                   len(full_answer), stream_exc)
                    if not full_answer:
                        yield _sse_event("chat_error", {
                            "error": "server_error",
                            "message": "Une erreur est survenue. Veuillez réessayer.",
                        })
                        return

                # 7. Persistance (pour analytics prospect + claim futur au signup).
                await service.add_message(
                    conversation_id=conversation.id, role="user", content=message,
                )
                assistant_message = await service.add_message(
                    conversation_id=conversation.id, role="assistant",
                    content=full_answer,
                    sources=sources_dicts if sources_dicts else None,
                )
                try:
                    total_latency_ms = int((time.perf_counter() - t_total) * 1000)
                    rag_trace.perf_ms["total"] = float(total_latency_ms)
                    # Trace persistée comme pour le chat réel → les questions
                    # démo apparaissent dans le BO Qualité admin (taguées via
                    # l'org démo « AORIA RH — Démo publique »).
                    assistant_message.rag_trace = rag_trace.to_dict()
                    assistant_message.question_id = question_id
                    assistant_message.latency_ms = total_latency_ms
                    await db.commit()
                except Exception:
                    logger.exception("Démo: échec persistance trace")

                yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})

            except Exception:
                logger.exception("Démo: erreur SSE")
                yield _sse_event("chat_error", {
                    "error": "server_error",
                    "message": "Une erreur est survenue lors du traitement. Réessayez.",
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
