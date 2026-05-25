import logging
from datetime import UTC, datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_CONTACTS_URL = "https://api.brevo.com/v3/contacts"


def _brevo_headers() -> dict[str, str]:
    return {
        "api-key": settings.brevo_api_key,
        "Content-Type": "application/json",
    }


async def send_email(
    to_email: str,
    to_name: str | None,
    subject: str,
    html_content: str,
) -> bool:
    """Send a transactional email via Brevo. Returns True on success."""
    if not settings.brevo_api_key:
        logger.warning("Brevo API key not configured, skipping email to %s", to_email)
        return False

    payload = {
        "sender": {"name": "AORIA RH", "email": "noreply@aoriarh.fr"},
        "to": [{"email": to_email, "name": to_name or to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            BREVO_API_URL,
            json=payload,
            headers=_brevo_headers(),
            timeout=10.0,
        )

    if response.status_code in (200, 201):
        logger.info("Email sent to %s: %s", to_email, subject)
        return True

    logger.error("Brevo API error %s: %s", response.status_code, response.text)
    return False


async def sync_contact_to_brevo(
    email: str,
    full_name: str | None,
    auth_method: str,
    role: str,
) -> bool:
    """Create or update a contact in Brevo and add to the clients list.

    Best-effort: returns False on any failure, never raises.
    """
    if not settings.brevo_api_key or not settings.brevo_list_id:
        return False

    first_name, _, last_name = (full_name or "").partition(" ")

    payload: dict = {
        "email": email,
        "attributes": {
            "PRENOM": first_name,
            "NOM": last_name,
            "METHODE_INSCRIPTION": auth_method,
            "ROLE": role,
            "DATE_INSCRIPTION": datetime.now(UTC).strftime("%Y-%m-%d"),
        },
        "listIds": [settings.brevo_list_id],
        "updateEnabled": True,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                BREVO_CONTACTS_URL,
                json=payload,
                headers=_brevo_headers(),
                timeout=10.0,
            )
        if response.status_code in (200, 201, 204):
            logger.info("Brevo contact synced: %s", email)
            return True
        logger.error("Brevo contacts API error %s: %s", response.status_code, response.text)
    except Exception:
        logger.exception("Failed to sync contact to Brevo: %s", email)
    return False
