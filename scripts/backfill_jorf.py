"""Rattrapage historique des textes JORF (lois / ordonnances / décrets).

Contexte : la synchro hebdomadaire (`run_jorf_sync`) ne balaie que les 30
derniers jours de publication et n'a été allumée que le 28 mai 2026. Tout ce qui
précède n'a jamais été présenté au filtre — d'où un corpus à ~9 % de couverture
mesuré contre les textes cités par le Code du travail numérique.

Ce script comble le passé. Il réutilise JorfService (auth PISTE, /search,
/consult, création de Document) mais s'en écarte sur deux points :

  * SANS filtre RH par défaut (--filtre-rh pour le réactiver). Le filtre par
    mots-clés est justement le maillon qu'on ne sait pas valider : sur les
    natures substantielles (lois/ordonnances/décrets) le volume est assez faible
    pour tout prendre et supprimer la question du rappel.
  * Fenêtre découpée MOIS PAR MOIS. La recherche LODA plafonne à
    _MAX_PAGES × _PAGE_SIZE = 2 000 résultats par fenêtre ; une fenêtre annuelle
    (2 717 textes en 2020) dépasserait ce plafond et perdrait des textes en
    silence.

Idempotent : la dédup par CID (Document.numero_pourvoi) est relue à chaque
fenêtre, donc le script peut être relancé après une interruption sans re-ingérer.

Usage :
    # 1. Compter sans rien écrire (aucun /consult, aucune ingestion)
    docker compose -f docker-compose.prod.yml exec backend \
        python scripts/backfill_jorf.py --debut 2020-01-01 --fin 2026-05-28 --dry-run

    # 2. Lancer pour de vrai, une année à la fois
    docker compose -f docker-compose.prod.yml exec backend \
        python scripts/backfill_jorf.py --debut 2020-01-01 --fin 2020-12-31
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date

import httpx
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.user import User
from app.rag.tasks import enqueue_ingestion
from app.services.jorf_service import (
    _NATURE_TO_SOURCE_TYPE,
    JorfService,
    JorfSyncResult,
    JorfText,
    _is_rh_relevant,
)
from app.services.storage_service import StorageService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("backfill_jorf")

# Délai entre deux /consult. PISTE tolère mal les rafales et le backfill n'est
# pas pressé : il tourne à côté du trafic utilisateur, qui reste prioritaire.
_CONSULT_DELAY = 0.15


def _mois(debut: date, fin: date) -> list[tuple[date, date]]:
    """Découpe [debut, fin] en fenêtres mensuelles (plafond LODA de 2 000)."""
    fenetres: list[tuple[date, date]] = []
    curseur = debut.replace(day=1)
    while curseur <= fin:
        if curseur.month == 12:
            suivant = curseur.replace(year=curseur.year + 1, month=1)
        else:
            suivant = curseur.replace(month=curseur.month + 1)
        fin_mois = date.fromordinal(suivant.toordinal() - 1)
        fenetres.append((max(curseur, debut), min(fin_mois, fin)))
        curseur = suivant
    return fenetres


async def _admin_id() -> str:
    async with async_session_factory() as db:
        res = await db.execute(
            select(User).where(User.role == "admin", User.is_active.is_(True)).limit(1)
        )
        admin = res.scalar_one_or_none()
        if not admin:
            sys.exit("Aucun admin actif en base — impossible de rattacher les documents.")
        return str(admin.id)


async def _fenetre(
    svc: JorfService,
    client: httpx.AsyncClient,
    db,
    storage,
    user_id,
    debut: date,
    fin: date,
    natures: list[str],
    dry_run: bool,
    filtre_rh: bool,
    vus: set[str],
) -> tuple[int, int, int, int]:
    """Traite une fenêtre mensuelle. Retourne (listés, ingérés, ignorés, erreurs)."""
    res = JorfSyncResult()
    lignes = await svc._search_all(client, debut, fin, res)

    if res.total_fetched >= 2000:
        logger.warning(
            "%s → %s : %d résultats, PLAFOND LODA ATTEINT — des textes sont "
            "perdus, il faut découper plus fin",
            debut, fin, res.total_fetched,
        )

    listes = ingeres = ignores = erreurs = 0
    for ligne in lignes:
        cid, titre, nature = svc._parse_search_result(ligne)
        if not cid or nature not in natures:
            continue
        listes += 1
        if cid in vus:
            ignores += 1
            continue

        if dry_run:
            vus.add(cid)
            ingeres += 1
            continue

        # Un texte qui casse ne doit jamais emporter le rattrapage entier :
        # PISTE renvoie des 400 sur certains CID (textes retirés, CID mal formés).
        # On journalise, on marque le CID comme vu et on continue.
        try:
            consult = await svc._api_post(client, "/consult/jorf", {"textCid": cid})
            await asyncio.sleep(_CONSULT_DELAY)
            if not consult:
                logger.warning("consult vide : %s (%s)", cid, titre[:70])
                vus.add(cid)
                erreurs += 1
                continue

            texte, codes_modifies, pub_date = svc._parse_consult(consult)
            if filtre_rh and not _is_rh_relevant(titre, codes_modifies):
                vus.add(cid)
                ignores += 1
                continue
            if not texte or len(texte) < 50:
                logger.warning("texte vide : %s (%s)", cid, titre[:70])
                vus.add(cid)
                erreurs += 1
                continue

            doc = await svc._create_document(
                db,
                JorfText(cid=cid, title=titre, nature=nature, text=texte,
                         publication_date=pub_date),
                user_id,
                storage,
            )
            await enqueue_ingestion(str(doc.id))
            vus.add(cid)
            ingeres += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ERREUR sur %s (%s) : %s", cid, titre[:60], str(exc)[:150]
            )
            await db.rollback()
            vus.add(cid)
            erreurs += 1

    return listes, ingeres, ignores, erreurs


async def main() -> None:
    p = argparse.ArgumentParser(description="Rattrapage historique JORF")
    p.add_argument("--debut", required=True, help="AAAA-MM-JJ")
    p.add_argument("--fin", required=True, help="AAAA-MM-JJ")
    p.add_argument(
        "--natures", default="LOI,ORDONNANCE,DECRET",
        help="Natures LODA (défaut : LOI,ORDONNANCE,DECRET — les arrêtés sont "
             "exclus : ~29 500 textes pour l'essentiel du bruit)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Compte seulement : aucun /consult, aucune écriture, aucune ingestion",
    )
    p.add_argument(
        "--filtre-rh", action="store_true",
        help="Réapplique le filtre RH par mots-clés (défaut : on prend tout)",
    )
    args = p.parse_args()

    debut = date.fromisoformat(args.debut)
    fin = date.fromisoformat(args.fin)
    natures = [n.strip().upper() for n in args.natures.split(",")]
    inconnues = set(natures) - set(_NATURE_TO_SOURCE_TYPE)
    if inconnues:
        sys.exit(f"Natures inconnues : {', '.join(sorted(inconnues))}")

    svc = JorfService()
    if not svc._client_id or not svc._client_secret:
        sys.exit("Credentials PISTE absents de l'environnement.")

    user_id = await _admin_id()
    storage = StorageService()
    fenetres = _mois(debut, fin)

    logger.info(
        "Rattrapage %s → %s | natures=%s | filtre_rh=%s | dry_run=%s | %d fenêtres",
        debut, fin, ",".join(natures), args.filtre_rh, args.dry_run, len(fenetres),
    )

    t_listes = t_ingeres = t_ignores = t_erreurs = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with async_session_factory() as db:
            vus = await svc._get_existing_cids(db)
            logger.info("%d CID déjà en base (dédup)", len(vus))

            for i, (d, f) in enumerate(fenetres, 1):
                try:
                    listes, ingeres, ignores, erreurs = await _fenetre(
                        svc, client, db, storage, user_id, d, f, natures,
                        args.dry_run, args.filtre_rh, vus,
                    )
                except Exception as exc:  # noqa: BLE001
                    # Une fenêtre qui casse (panne PISTE, /search KO) ne doit pas
                    # emporter les 76 autres : le mois est relançable tel quel.
                    logger.error("FENÊTRE %s ÉCHOUÉE : %s", d.strftime("%Y-%m"),
                                 str(exc)[:200])
                    await db.rollback()
                    t_erreurs += 1
                    continue
                t_listes += listes
                t_ingeres += ingeres
                t_ignores += ignores
                t_erreurs += erreurs
                logger.info(
                    "[%d/%d] %s : %d listés, %d %s, %d ignorés, %d erreurs "
                    "(cumul ingérés : %d)",
                    i, len(fenetres), d.strftime("%Y-%m"), listes, ingeres,
                    "à ingérer" if args.dry_run else "ingérés", ignores, erreurs,
                    t_ingeres,
                )

    logger.info(
        "TERMINÉ — %d listés, %d %s, %d ignorés, %d erreurs",
        t_listes, t_ingeres,
        "seraient ingérés" if args.dry_run else "ingérés", t_ignores, t_erreurs,
    )
    if args.dry_run:
        logger.info("Rien n'a été écrit (--dry-run).")


if __name__ == "__main__":
    asyncio.run(main())
