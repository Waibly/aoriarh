import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


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
            headers={
                "api-key": settings.brevo_api_key,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    if response.status_code in (200, 201):
        logger.info("Email sent to %s: %s", to_email, subject)
        return True

    logger.error("Brevo API error %s: %s", response.status_code, response.text)
    return False
