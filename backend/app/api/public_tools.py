"""Notifications anonymisées d'utilisation des outils gratuits Aoria RH.

L'endpoint est public parce que les calculateurs vivent sur aoriarh.fr, mais
il n'accepte qu'un contrat fermé et agrégé. Les valeurs exactes et les données
de santé ne doivent jamais quitter le navigateur.
"""

import hashlib
import hmac
import html
import json
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from slowapi.util import get_remote_address

from app.core.config import settings
from app.services.email.sender import send_email

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_BODY_BYTES = 12_000
_TURNSTILE_ACTION = "dismissal_calculation"
_redis_client = None


class ToolAcquisition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    utm_source: str | None = Field(default=None, max_length=80)
    utm_medium: str | None = Field(default=None, max_length=80)
    utm_campaign: str | None = Field(default=None, max_length=120)
    referrer_domain: str | None = Field(default=None, max_length=253)


class DismissalToolSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    usage_id: UUID
    schema_version: Literal["1"]
    tool_id: Literal["dismissal_indemnity"]
    turnstile_token: str = Field(min_length=1, max_length=2_048)
    agreement_scope: Literal[
        "ccn_0413", "ccn_1486", "ccn_1979", "other_ccn", "unknown_ccn", "no_ccn"
    ]
    professional_category: Literal[
        "non_cadre", "cadre", "cadre_direction", "etam", "engineer_cadre", "not_applicable"
    ]
    salary_mode: Literal["stable_monthly", "monthly_detail"]
    salary_bracket: Literal[
        "under_2k", "2k_3k", "3k_4k", "4k_6k", "6k_10k", "10k_plus"
    ]
    seniority_bracket: Literal[
        "under_8m", "8m_2y", "2y_5y", "5y_10y", "10y_20y", "20y_plus"
    ]
    legal_amount_bracket: Literal[
        "zero", "under_5k", "5k_10k", "10k_25k", "25k_50k", "50k_100k", "100k_plus"
    ]
    agreement_amount_bracket: Literal[
        "not_calculated",
        "review_required",
        "zero",
        "under_5k",
        "5k_10k",
        "10k_25k",
        "25k_50k",
        "50k_100k",
        "100k_plus",
    ]
    selected_amount_bracket: Literal[
        "review_required",
        "zero",
        "under_5k",
        "5k_10k",
        "10k_25k",
        "25k_50k",
        "50k_100k",
        "100k_plus",
    ]
    result_scope: Literal[
        "comparison", "legal_only_complete", "legal_only_incomplete", "review_required"
    ]
    outcome: Literal[
        "legal", "agreement", "equal", "legal_only", "not_due", "review_required"
    ]
    has_absences: bool
    has_variable_compensation: bool
    has_complex_case: bool
    viewport: Literal["mobile", "tablet", "desktop"]
    browser_language: str = Field(min_length=2, max_length=16, pattern=r"^[A-Za-z-]+$")
    timezone: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+./-]+$")
    acquisition: ToolAcquisition


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",", 1)[0].strip()
    return first or get_remote_address(request)


def _anonymous_ip_key(request: Request) -> str:
    digest = hmac.new(
        settings.secret_key.encode(),
        _client_ip(request).encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:24]


def _assert_browser_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").rstrip("/")
    if origin not in settings.tool_usage_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origine refusée.")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in {"same-origin", "same-site"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origine refusée.")


async def _verify_turnstile(token: str, remote_ip: str) -> bool:
    if not settings.turnstile_secret:
        logger.error("Notifications outils: TURNSTILE_SECRET absent")
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": settings.turnstile_secret,
                    "response": token,
                    "remoteip": remote_ip,
                },
            )
        verification = response.json()
        return bool(
            verification.get("success")
            and verification.get("action") == _TURNSTILE_ACTION
            and str(verification.get("hostname", "")).lower()
            in settings.tool_usage_hostnames
        )
    except Exception:
        logger.exception("Notifications outils: vérification Turnstile indisponible")
        return False


async def _enforce_rate_limit(request: Request) -> None:
    """Limite le trafic avant même l'appel Turnstile. Panne Redis = refus."""
    now = datetime.now(UTC)
    ip_key = _anonymous_ip_key(request)
    minute = now.strftime("%Y%m%d%H%M")
    day = now.strftime("%Y%m%d")
    redis = _get_redis()
    pipe = redis.pipeline()
    pipe.incr(f"tools:mail:ipmin:{minute}:{ip_key}")
    pipe.expire(f"tools:mail:ipmin:{minute}:{ip_key}", 120)
    pipe.incr(f"tools:mail:ipday:{day}:{ip_key}")
    pipe.expire(f"tools:mail:ipday:{day}:{ip_key}", 90_000)
    pipe.incr(f"tools:mail:global:{minute}")
    pipe.expire(f"tools:mail:global:{minute}", 120)
    ip_min, _, ip_day, _, global_minute, _ = await pipe.execute()
    if int(ip_min) > 3 or int(ip_day) > 20 or int(global_minute) > 60:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de notifications en peu de temps.",
        )


async def _reserve_delivery(usage_id: UUID) -> Literal["accepted", "duplicate"]:
    """Déduplique un éventuel retry navigateur pendant 24 heures."""
    redis = _get_redis()
    reserved = await redis.set(f"tools:mail:usage:{usage_id}", "1", ex=86_400, nx=True)
    return "accepted" if reserved else "duplicate"


_LABELS = {
    "ccn_0413": "CCN 66 (IDCC 0413)",
    "ccn_1486": "Syntec (IDCC 1486)",
    "ccn_1979": "HCR (IDCC 1979)",
    "other_ccn": "Autre CCN",
    "unknown_ccn": "CCN inconnue",
    "no_ccn": "Sans CCN",
    "stable_monthly": "Salaire stable",
    "monthly_detail": "Mois détaillés",
    "review_required": "Vérification nécessaire",
    "legal_only_complete": "Légal uniquement — complet",
    "legal_only_incomplete": "Légal uniquement — autre CCN non calculée",
    "comparison": "Comparaison légal / CCN",
    "legal": "Minimum légal plus favorable",
    "agreement": "Minimum conventionnel plus favorable",
    "equal": "Montants identiques",
    "legal_only": "Résultat légal uniquement",
    "not_due": "Aucune indemnité due",
}


def _display(value: object) -> str:
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    text = str(value)
    return _LABELS.get(text, text.replace("_", " "))


def _email_html(summary: DismissalToolSummary) -> str:
    rows = [
        ("Outil", "Indemnité de licenciement — légal versus CCN"),
        ("Utilisation", summary.usage_id),
        ("Convention", summary.agreement_scope),
        ("Catégorie", summary.professional_category),
        ("Mode de rémunération", summary.salary_mode),
        ("Salaire de référence", summary.salary_bracket),
        ("Ancienneté", summary.seniority_bracket),
        ("Montant légal", summary.legal_amount_bracket),
        ("Montant conventionnel", summary.agreement_amount_bracket),
        ("Minimum retenu", summary.selected_amount_bracket),
        ("Portée du résultat", summary.result_scope),
        ("Issue", summary.outcome),
        ("Absences déclarées", summary.has_absences),
        ("Rémunération variable", summary.has_variable_compensation),
        ("Cas complexe signalé", summary.has_complex_case),
        ("Écran", summary.viewport),
        ("Langue du navigateur", summary.browser_language),
        ("Fuseau horaire", summary.timezone),
        ("Source UTM", summary.acquisition.utm_source or "—"),
        ("Support UTM", summary.acquisition.utm_medium or "—"),
        ("Campagne UTM", summary.acquisition.utm_campaign or "—"),
        ("Domaine référent", summary.acquisition.referrer_domain or "—"),
    ]
    table = "".join(
        "<tr>"
        "<th style='padding:8px 12px;text-align:left;"
        f"border-bottom:1px solid #e8e5ee'>{html.escape(label)}</th>"
        "<td style='padding:8px 12px;"
        f"border-bottom:1px solid #e8e5ee'>{html.escape(_display(value))}</td>"
        "</tr>"
        for label, value in rows
    )
    generated_at = datetime.now(UTC).strftime("%d/%m/%Y à %H:%M UTC")
    return (
        "<div style='font-family:Arial,sans-serif;color:#151321;max-width:720px'>"
        "<h1 style='font-size:22px'>Nouvelle utilisation du simulateur</h1>"
        f"<p>Calcul abouti le {generated_at}. Les valeurs sont volontairement regroupées "
        "par tranches et ne contiennent ni identité, ni IP, ni dates ou montants exacts.</p>"
        f"<table style='border-collapse:collapse;width:100%;font-size:14px'>{table}</table>"
        "</div>"
    )


@router.post("/dismissal-indemnity", status_code=status.HTTP_202_ACCEPTED)
async def notify_dismissal_tool_usage(request: Request) -> dict[str, str]:
    if not settings.tool_usage_notifications_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fonction désactivée.")
    _assert_browser_origin(request)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from None
    if content_length < 0 or content_length > _MAX_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    try:
        summary = DismissalToolSummary.model_validate_json(bytes(body))
    except (ValidationError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Résumé d'utilisation invalide.",
        ) from None

    try:
        await _enforce_rate_limit(request)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Notifications outils: Redis indisponible, envoi refusé")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification momentanément indisponible.",
        ) from None
    if not await _verify_turnstile(summary.turnstile_token, _client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vérification anti-robot échouée.",
        )
    try:
        reservation = await _reserve_delivery(summary.usage_id)
    except Exception:
        logger.exception("Notifications outils: Redis indisponible, envoi refusé")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification momentanément indisponible.",
        ) from None
    if reservation == "duplicate":
        return {"status": "accepted"}

    try:
        delivered = await send_email(
            settings.tool_usage_notification_email,
            "Vanessa",
            "Nouvelle utilisation — simulateur indemnité de licenciement",
            _email_html(summary),
        )
    except Exception:
        delivered = False
        logger.exception("Notifications outils: échec d'envoi Brevo")
    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification momentanément indisponible.",
        )
    return {"status": "accepted"}
