"""Alertes internes pour les demandes sensibles adressées à l'assistant.

Ces alertes sont volontairement hors du chemin critique du chat : une panne
Redis ou Brevo ne doit jamais ralentir ni casser la réponse de sécurité.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from html import escape

from app.core.config import settings
from app.services.email.sender import send_email

logger = logging.getLogger(__name__)

EVENT_TECHNICAL_RECON = "technical_reconnaissance"
EVENT_PROTECTED_DATA = "protected_data_request"
EVENT_PRIVILEGE_CLAIM = "privilege_claim"
EVENT_INSTRUCTION_BYPASS = "instruction_bypass"

_EVENT_LABELS = {
    EVENT_TECHNICAL_RECON: "Question sur le fonctionnement interne",
    EVENT_PROTECTED_DATA: "Demande de données internes ou tierces",
    EVENT_PRIVILEGE_CLAIM: "Tentative d'étendre les droits dans la conversation",
    EVENT_INSTRUCTION_BYPASS: "Tentative de contourner les instructions",
}

# Une alerte immédiate par utilisateur et catégorie, puis silence temporaire.
# Le plafond journalier protège également la boîte en cas de catégories variées.
_CATEGORY_COOLDOWN_SECONDS = 60 * 60
_MAX_ALERTS_PER_USER_PER_DAY = 5
_QUERY_MAX_CHARS = 2000

_SENSITIVE_QUERY_PATTERNS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer [MASQUÉ]"),
    (
        re.compile(
            r"(?i)\b(api[_ -]?key|token|secret|password|mot de passe)\s*[:=]\s*\S+"
        ),
        r"\1=[MASQUÉ]",
    ),
    (
        re.compile(r"\b(?:sk|pk|va|ghp|xoxb)[_-][A-Za-z0-9_-]{12,}\b", re.IGNORECASE),
        "[SECRET MASQUÉ]",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[EMAIL MASQUÉ]",
    ),
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "[VALEUR LONGUE MASQUÉE]"),
)

_redis_client = None
_background_tasks: set[asyncio.Task] = set()


def _redact_query(query: str) -> str:
    redacted = (query or "")[:_QUERY_MAX_CHARS]
    for pattern, replacement in _SENSITIVE_QUERY_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def _reserve_alert(user_id: str, event_type: str) -> bool:
    """Réserve une alerte distribuée. Redis indisponible = pas d'e-mail.

    Le refus en cas de panne est volontaire : la protection utilisateur reste
    active, tandis qu'un attaquant ne peut pas transformer la panne du limiteur
    en rafale d'e-mails.
    """
    try:
        redis = _get_redis()
        category_key = f"security-alert:cooldown:{user_id}:{event_type}"
        reserved = await redis.set(
            category_key, "1", ex=_CATEGORY_COOLDOWN_SECONDS, nx=True,
        )
        if not reserved:
            return False

        day = datetime.now(UTC).strftime("%Y-%m-%d")
        daily_key = f"security-alert:daily:{user_id}:{day}"
        daily_count = await redis.incr(daily_key)
        if daily_count == 1:
            await redis.expire(daily_key, 172_800)
        return daily_count <= _MAX_ALERTS_PER_USER_PER_DAY
    except Exception:
        logger.exception("[SECURITY] Redis indisponible — alerte e-mail ignorée")
        return False


async def send_security_alert(
    *,
    event_type: str,
    query: str,
    user_id: str,
    user_email: str,
    user_name: str,
    user_role: str,
    organisation_id: str,
    organisation_name: str | None,
    conversation_id: str,
    message_id: str,
    detected_via: str,
) -> bool:
    """Envoie une alerte minimisée, échappée et limitée en fréquence."""
    if not settings.security_alerts_enabled or not settings.security_alert_email:
        return False
    if not await _reserve_alert(user_id, event_type):
        return False

    label = _EVENT_LABELS.get(event_type, "Demande sensible")
    safe = {
        "label": escape(label),
        "query": escape(_redact_query(query)),
        "user_id": escape(user_id),
        "user_email": escape(user_email),
        "user_name": escape(user_name),
        "user_role": escape(user_role),
        "organisation_id": escape(organisation_id),
        "organisation_name": escape(organisation_name or "—"),
        "conversation_id": escape(conversation_id),
        "message_id": escape(message_id),
        "detected_via": escape(detected_via),
        "detected_at": datetime.now(UTC).strftime("%d/%m/%Y à %H:%M:%S UTC"),
    }

    subject = f"[AORIA RH] Demande sensible détectée — {label}"
    html_content = f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;color:#27272a">
      <h2 style="color:#652BB0">Demande sensible détectée</h2>
      <p><strong>Catégorie :</strong> {safe['label']}</p>
      <div style="background:#f4f4f5;border-left:4px solid #652BB0;padding:14px;
                  margin:16px 0;white-space:pre-wrap;overflow-wrap:anywhere">{safe['query']}</div>
      <table style="border-collapse:collapse;font-size:13px">
        <tr><td style="padding:4px 12px 4px 0"><strong>Utilisateur</strong></td>
            <td>{safe['user_name']} — {safe['user_email']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Rôle</strong></td>
            <td>{safe['user_role']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Organisation</strong></td>
            <td>{safe['organisation_name']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>User ID</strong></td>
            <td>{safe['user_id']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Organisation ID</strong></td>
            <td>{safe['organisation_id']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Conversation ID</strong></td>
            <td>{safe['conversation_id']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Message ID</strong></td>
            <td>{safe['message_id']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Détection</strong></td>
            <td>{safe['detected_via']}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Date</strong></td>
            <td>{safe['detected_at']}</td></tr>
      </table>
      <p style="color:#71717a;font-size:12px;margin-top:18px">
        Aucune adresse IP, donnée d'un autre client, secret ou contexte technique
        n'est joint à cette alerte. Les répétitions sont limitées automatiquement.
      </p>
    </div>
    """

    try:
        return await send_email(
            to_email=settings.security_alert_email,
            to_name="Sécurité AORIA RH",
            subject=subject,
            html_content=html_content,
        )
    except Exception:
        logger.exception("[SECURITY] Échec d'envoi de l'alerte")
        return False


def send_security_alert_bg(**kwargs) -> None:
    """Programme l'alerte sans ajouter de latence au flux de réponse."""
    try:
        task = asyncio.get_running_loop().create_task(send_security_alert(**kwargs))
    except RuntimeError:
        logger.warning("[SECURITY] Alerte appelée hors event loop — ignorée")
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def flush_security_alerts() -> None:
    """Attend les alertes en cours (principalement destiné aux tests)."""
    if _background_tasks:
        await asyncio.gather(*tuple(_background_tasks), return_exceptions=True)
