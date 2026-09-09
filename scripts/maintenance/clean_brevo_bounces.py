"""Nettoyage manuel : supprime de Brevo les contacts qui ont rebondi (bounce).

Le moteur d'emailing fait DÉJÀ ce nettoyage tout seul à chaque passage
(cron horaire + bouton « envoyer maintenant ») via
``emailing_service.purge_bounced_contacts``. Ce script sert aux cas
ponctuels : rattraper un gros backlog sans attendre le cron, ou inspecter
ce qui serait supprimé (dry-run).

Par défaut : DRY-RUN (liste sans rien supprimer). Ajouter --apply pour
exécuter réellement.

Usage (depuis le conteneur backend) :
    # Aperçu (ne supprime rien) :
    docker compose exec -T backend python /app/clean_brevo_bounces.py

    # Suppression réelle :
    docker compose exec -T backend python /app/clean_brevo_bounces.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.core.config import settings
from app.core.database import async_session_factory
from app.services.emailing_service import purge_bounced_contacts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("clean_brevo_bounces")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Exécute réellement les suppressions (sinon: dry-run).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100_000,
        help="Nombre maximum d'adresses à traiter (défaut: tout).",
    )
    args = parser.parse_args()

    if not settings.brevo_api_key:
        logger.error("BREVO_API_KEY non configurée — abandon.")
        return 1

    async with async_session_factory() as db:
        if not args.apply:
            await purge_bounced_contacts(db, limit=args.limit, dry_run=True)
            logger.info("Dry-run terminé. Relancer avec --apply pour supprimer.")
            return 0

        purged = await purge_bounced_contacts(db, limit=args.limit)
        logger.info("Terminé : %d contact(s) supprimé(s) de Brevo.", purged)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
