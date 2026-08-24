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
  2. Rate-limit par IP RÉELLE du visiteur (X-Forwarded-For) + plafond global par
     minute, via Redis (partagé entre les workers, fail-open).
  3. Plafond de dépense quotidien global (`demo_daily_budget_eur`), mesuré sur
     les coûts réels attribués à l'org démo dans `api_usage_logs`.
"""

import asyncio
import dataclasses
import hashlib
import ipaddress
import logging
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import (
    _SLOW_CONTEXT_NOTICE,
    _SLOW_GENERATION_NOTICE,
    _load_org_context,
    _sse_event,
    _stream_with_idle_guard,
)
from app.core.config import settings
from app.core.database import async_session_factory
from app.models.api_usage import ApiUsageLog
from app.models.conversation import Conversation
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.agent import (
    _OUT_OF_SCOPE_ANSWER,
    _OUT_OF_SCOPE_MARKER,
    RAGAgent,
)
from app.rag.config import (
    RAG_SLOW_NOTICE,
    RAG_TIMEOUT_CONTEXT,
    RAG_TIMEOUT_STREAM_IDLE,
)
from app.rag.intent_router import classify_intent
from app.rag.pipeline import prepare_rag_context
from app.services.conversation_service import ConversationService
from app.services.security_alert_service import send_security_alert_bg

logger = logging.getLogger(__name__)

router = APIRouter()

_redis_client = None


def _get_redis():
    """Client Redis asyncio partagé (lazy). Même pattern qu'admin_costs."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _client_ip(request: Request) -> str:
    """IP RÉELLE du visiteur derrière le reverse proxy Caddy.

    `request.client.host` = IP interne de Caddy (réseau Docker). Caddy renseigne
    l'IP d'origine dans X-Forwarded-For (le 1er maillon est le client réel).
    """
    peer = get_remote_address(request)
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted_proxy = peer_ip.is_loopback or peer_ip.is_private
    except ValueError:
        trusted_proxy = False
    if trusted_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            for candidate in reversed([part.strip() for part in xff.split(",")]):
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
    return peer


async def _demo_rate_limit_ok(request: Request) -> bool:
    """Rate-limit démo par IP RÉELLE + plafond global/minute, via Redis (partagé
    entre les workers gunicorn). Fail-open : toute erreur Redis → on autorise (le
    plafond de budget quotidien reste le garde-fou financier)."""
    try:
        ip = _client_ip(request)
        h = hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]  # IP hashée (RGPD)
        now = datetime.now(UTC)
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        k_ip_min = f"demo:rl:ipmin:{minute}:{h}"
        k_ip_day = f"demo:rl:ipday:{day}:{h}"
        k_glob_min = f"demo:rl:globmin:{minute}"

        r = _get_redis()
        pipe = r.pipeline()
        pipe.incr(k_ip_min)
        pipe.expire(k_ip_min, 120)
        pipe.incr(k_ip_day)
        pipe.expire(k_ip_day, 90_000)
        pipe.incr(k_glob_min)
        pipe.expire(k_glob_min, 120)
        ip_min, _, ip_day, _, glob_min, _ = await pipe.execute()

        if int(ip_min) > settings.demo_max_questions_per_ip_per_minute:
            return False
        if int(ip_day) > settings.demo_max_questions_per_ip_per_day:
            return False
        if int(glob_min) > settings.demo_max_questions_global_per_minute:
            return False
        return True
    except Exception:
        logger.warning("Démo: rate-limit Redis indisponible")
        return not settings.is_production


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
    model_config = {"extra": "forbid"}

    message: str = Field(..., min_length=1)
    # Jeton Turnstile (ignoré si la vérification est désactivée côté serveur).
    turnstile_token: str | None = None


async def _resolve_demo_ids(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Retourne (org_id, user_id) de la démo, seedés au démarrage (main.seed_demo).

    503 si absents : l'endpoint ne doit jamais improviser une org/user.
    """
    if "org" in _demo_ids and "user" in _demo_ids:
        return _demo_ids["org"], _demo_ids["user"]

    org_id = (
        await db.execute(select(Organisation.id).where(Organisation.name == settings.demo_org_name))
    ).scalar_one_or_none()
    user_id = (
        await db.execute(select(User.id).where(User.email == settings.demo_user_email))
    ).scalar_one_or_none()

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
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        await db.execute(
            select(func.coalesce(func.sum(ApiUsageLog.cost_usd), 0)).where(
                ApiUsageLog.organisation_id == demo_org_id,
                ApiUsageLog.created_at >= today_start,
            )
        )
    ).scalar_one()
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
async def public_ask(
    data: PublicAskRequest,
    request: Request,
) -> StreamingResponse:
    """Pose une question de démo (non authentifié) et streame la réponse (SSE)."""
    if not settings.demo_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Démo désactivée")

    # 1. Anti-bot : Turnstile (avec l'IP réelle du visiteur)
    remote_ip = _client_ip(request)
    if not await _verify_turnstile(data.turnstile_token, remote_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vérification anti-robot échouée. Rechargez la page et réessayez.",
        )

    # 1b. Rate-limit par IP réelle (Redis, partagé entre workers)
    if not await _demo_rate_limit_ok(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Trop de questions en peu de temps. "
                "Créez un compte gratuit pour continuer sans limite."
            ),
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

            # Une conversation neuve par requête empêche un visiteur de reprendre
            # le contexte d'un autre visiteur à partir d'un UUID divulgué.
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
                    meta_user = await service.add_message(
                        conversation_id=conversation.id,
                        role="user",
                        content=message,
                    )
                    meta_assistant = await service.add_message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=intent_result.static_answer,
                    )
                    # La démo ne propose pas la fiche, mais on persiste le même
                    # signal que le chat authentifié pour garder un historique
                    # cohérent et auditable.
                    meta_assistant.rag_trace = {
                        "static_intent": intent_result.intent.value,
                        "security_event": intent_result.security_event,
                    }
                    await db.commit()
                    if intent_result.security_event is not None:
                        # Tous les visiteurs partagent le même user technique :
                        # le limiteur Redis agrège donc les alertes de la démo et
                        # empêche d'utiliser cet endpoint pour spammer la boîte.
                        send_security_alert_bg(
                            event_type=intent_result.security_event,
                            query=message,
                            user_id=str(demo_user_id),
                            user_email=settings.demo_user_email,
                            user_name="Visiteur démo publique",
                            user_role="public_demo",
                            organisation_id=str(demo_org_id),
                            organisation_name="Démo publique",
                            conversation_id=str(conversation.id),
                            message_id=str(meta_user.id),
                            detected_via=intent_result.via,
                        )
                    yield _sse_event("chat_delta", {"content": intent_result.static_answer})
                    yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})
                    return

                yield _sse_event("chat_status", {"step": "Analyse de votre question..."})

                # 4. Préparation du contexte. org_idcc_list=None → corpus commun
                # strict (aucune CCN). question_id = contexte de coût.
                question_id = uuid.uuid4()
                ctx_task = asyncio.ensure_future(
                    prepare_rag_context(
                        agent,
                        query=message,
                        organisation_id=str(demo_org_id),
                        org_context=org_context,
                        history=None,
                        cited_sources=None,
                        org_idcc_list=None,
                        user_id=str(demo_user_id),
                        context_id=str(question_id),
                    )
                )
                try:
                    try:
                        # Deux temps : message de patience à RAG_SLOW_NOTICE,
                        # borne globale ensuite (cf. conversations.py).
                        results, reformulated, rag_trace = await asyncio.wait_for(
                            asyncio.shield(ctx_task),
                            timeout=RAG_SLOW_NOTICE,
                        )
                    except TimeoutError:
                        yield _sse_event(
                            "chat_status",
                            {"step": _SLOW_CONTEXT_NOTICE},
                        )
                        results, reformulated, rag_trace = await asyncio.wait_for(
                            ctx_task,
                            timeout=max(RAG_TIMEOUT_CONTEXT - RAG_SLOW_NOTICE, 1.0),
                        )
                except TimeoutError:
                    logger.warning("Démo: prepare_context timeout (%.0fs)", RAG_TIMEOUT_CONTEXT)
                    yield _sse_event(
                        "chat_error",
                        {
                            "error": "timeout",
                            "message": (
                                "Le traitement a pris trop de temps. "
                                "Veuillez réessayer dans quelques instants."
                            ),
                        },
                    )
                    return

                if reformulated == _OUT_OF_SCOPE_MARKER:
                    await service.add_message(
                        conversation_id=conversation.id,
                        role="user",
                        content=message,
                    )
                    await service.add_message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content=_OUT_OF_SCOPE_ANSWER,
                    )
                    yield _sse_event("chat_delta", {"content": _OUT_OF_SCOPE_ANSWER})
                    yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})
                    return

                if not results:
                    yield _sse_event(
                        "chat_error",
                        {
                            "error": "no_results",
                            "message": (
                                "Je n'ai pas trouvé de source pertinente dans le socle "
                                "légal commun pour cette question. Créez un compte et "
                                "importez votre convention collective pour aller plus loin."
                            ),
                        },
                    )
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
                stream_dead = False
                try:
                    # Garde d'inactivité (cf. conversations.py) : une réponse
                    # qui avance n'est jamais coupée ; message de patience à
                    # RAG_SLOW_NOTICE, abandon du seul flux réellement mort.
                    async for kind, chunk in _stream_with_idle_guard(
                        agent.stream_generate(
                            message,
                            results,
                            # Pas de bloc « Entreprise de l'utilisateur » en démo :
                            # réponse générique, jamais « chez <une entreprise> ».
                            org_context=None,
                            history=None,
                            low_confidence=rag_trace.low_confidence,
                            condensed_query=reformulated,
                            model_override=settings.demo_llm_model,
                            answer_format=(
                                rag_trace.search_plan.get("answer_format")
                                if rag_trace.search_plan
                                and rag_trace.search_plan_usage.get("execution") == "adaptive"
                                else None
                            ),
                        ),
                        idle_timeout=RAG_TIMEOUT_STREAM_IDLE,
                        slow_notice=RAG_SLOW_NOTICE,
                    ):
                        if await request.is_disconnected():
                            return
                        if kind == "slow":
                            yield _sse_event(
                                "chat_status",
                                {"step": _SLOW_GENERATION_NOTICE},
                            )
                            continue
                        if kind == "dead":
                            stream_dead = True
                            break
                        full_answer += chunk
                        yield _sse_event("chat_delta", {"content": chunk})
                except Exception as stream_exc:
                    logger.warning(
                        "Démo: streaming interrompu (%d car.): %s", len(full_answer), stream_exc
                    )
                    if not full_answer:
                        yield _sse_event(
                            "chat_error",
                            {
                                "error": "server_error",
                                "message": "Une erreur est survenue. Veuillez réessayer.",
                            },
                        )
                        return

                if stream_dead:
                    logger.warning(
                        "Démo: flux muet %.0fs — abandonné (%d car.)",
                        RAG_TIMEOUT_STREAM_IDLE,
                        len(full_answer),
                    )
                    if not full_answer:
                        yield _sse_event(
                            "chat_error",
                            {
                                "error": "timeout",
                                "message": "La génération n'a pas pu démarrer. Réessayez.",
                            },
                        )
                        return
                    cut_notice = "\n\n*La génération s'est interrompue en cours de route.*"
                    full_answer += cut_notice
                    yield _sse_event("chat_delta", {"content": cut_notice})

                # 7. Persistance (pour analytics prospect + claim futur au signup).
                await service.add_message(
                    conversation_id=conversation.id,
                    role="user",
                    content=message,
                )
                assistant_message = await service.add_message(
                    conversation_id=conversation.id,
                    role="assistant",
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
                    await db.rollback()

                yield _sse_event("chat_done", {"upsell": _DEMO_UPSELL})

            except Exception:
                logger.exception("Démo: erreur SSE")
                yield _sse_event(
                    "chat_error",
                    {
                        "error": "server_error",
                        "message": "Une erreur est survenue lors du traitement. Réessayez.",
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
