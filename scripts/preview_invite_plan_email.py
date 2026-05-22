"""Aperçu du mail "plan Invité activé" : rendu + envoi de test à des adresses fixes.

Pas besoin de DB — on rend le template avec des valeurs d'exemple et on l'envoie
via Brevo (clé lue dans backend/.env). Le HTML est aussi écrit sur disque pour
ouverture rapide dans un navigateur.

Usage (depuis la racine du projet) :
    backend/.venv/bin/python scripts/preview_invite_plan_email.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Make `app.*` imports resolve against the backend package.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.services.email.sender import send_email  # noqa: E402
from app.services.email.templates import render_invite_plan_assigned_email  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("preview_invite_plan_email")

RECIPIENTS = [
    ("hello@waibly.com", "Équipe Waibly"),
    ("vanessa@aoriarh.fr", "Vanessa"),
]

SAMPLE_FULL_NAME = "Vanessa"
SAMPLE_EXPIRES_AT = datetime.now(UTC) + timedelta(days=90)  # 3 mois
SAMPLE_BILLING_URL = "https://app.aoriarh.fr/billing"

PREVIEW_HTML_PATH = Path(__file__).resolve().parent / "preview_invite_plan_email.html"


async def main() -> int:
    subject, html = render_invite_plan_assigned_email(
        full_name=SAMPLE_FULL_NAME,
        plan_expires_at=SAMPLE_EXPIRES_AT,
        billing_url=SAMPLE_BILLING_URL,
    )

    PREVIEW_HTML_PATH.write_text(html, encoding="utf-8")
    logger.info("Aperçu HTML écrit dans %s", PREVIEW_HTML_PATH)
    logger.info("Sujet : %s", subject)
    logger.info("Date d'expiration simulée : %s", SAMPLE_EXPIRES_AT.isoformat())

    failures = 0
    for email, name in RECIPIENTS:
        ok = await send_email(
            to_email=email,
            to_name=name,
            subject=subject,
            html_content=html,
        )
        if ok:
            logger.info("Envoyé à %s", email)
        else:
            logger.error("Échec d'envoi à %s", email)
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
