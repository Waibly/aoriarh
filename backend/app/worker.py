"""ARQ worker — processus séparé pour les tâches lourdes (ingestion, sync Judilibre).

Lancer avec :
    arq app.worker.WorkerSettings
"""

import os
import uuid
from datetime import date

from app.core.logging import setup_logging

setup_logging(json_output=os.getenv("LOG_FORMAT", "json") == "json")

import structlog
from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import select

from app.core.config import settings
from app.rag.ingestion import IngestionPipeline

logger = structlog.get_logger(__name__)


async def on_startup(ctx: dict) -> None:
    """Create shared DB engine and session factory at worker startup."""
    logger.info("Worker startup: creating shared DB engine")
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=8,
        max_overflow=4,
        pool_timeout=30,
        pool_recycle=1800,
    )
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def on_shutdown(ctx: dict) -> None:
    """Dispose DB engine on worker shutdown."""
    logger.info("Worker shutdown: disposing DB engine")
    engine = ctx.get("engine")
    if engine:
        await engine.dispose()


# --- SyncLog helpers ---------------------------------------------------------

async def _create_sync_log(
    session_factory,
    sync_type: str,
    idcc: str | None = None,
):
    """Create a SyncLog row with status='running' in its own session.

    Returns the row id (str). The caller must call _finish_sync_log later.
    Using a dedicated short session avoids holding a long transaction open.
    """
    from datetime import UTC, datetime
    from app.models.sync_log import SyncLog

    async with session_factory() as db:
        row = SyncLog(
            sync_type=sync_type,
            idcc=idcc,
            status="running",
            started_at=datetime.now(UTC),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return str(row.id)


async def _finish_sync_log(
    session_factory,
    sync_log_id: str,
    *,
    success: bool,
    items_fetched: int = 0,
    items_created: int = 0,
    items_updated: int = 0,
    items_skipped: int = 0,
    errors: int = 0,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Mark a SyncLog row as completed (success or error)."""
    from datetime import UTC, datetime
    from app.models.sync_log import SyncLog
    import uuid as _uuid

    async with session_factory() as db:
        row = await db.get(SyncLog, _uuid.UUID(sync_log_id))
        if row is None:
            return
        row.status = "success" if success else "error"
        row.items_fetched = items_fetched
        row.items_created = items_created
        row.items_updated = items_updated
        row.items_skipped = items_skipped
        row.errors = errors
        if error_message:
            row.error_message = error_message[:500]
        row.completed_at = datetime.now(UTC)
        if duration_ms is not None:
            row.duration_ms = duration_ms
        await db.commit()


async def run_ingestion(ctx: dict, document_id: str) -> None:
    """Tâche d'ingestion exécutée par le worker ARQ."""
    logger.info("Worker: ingestion started for document %s", document_id)
    session_factory = ctx["session_factory"]
    try:
        async with session_factory() as db:
            pipeline = IngestionPipeline()
            await pipeline.ingest(uuid.UUID(document_id), db)
        logger.info("Worker: ingestion completed for document %s", document_id)
    except Exception:
        logger.exception("Worker: ingestion failed for document %s", document_id)


async def run_judilibre_sync(
    ctx: dict,
    user_id: str,
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    chamber: str = "soc",
    publication: str = "b",
    max_decisions: int | None = None,
) -> None:
    """Tâche de synchronisation Judilibre exécutée par le worker ARQ."""
    logger.info("Worker: Judilibre sync started (chamber=%s, pub=%s)", chamber, publication)
    session_factory = ctx["session_factory"]
    try:
        from app.services.judilibre_service import JudilibreService

        service = JudilibreService()
        async with session_factory() as db:
            result = await service.sync(
                db=db,
                user_id=uuid.UUID(user_id),
                date_start=date.fromisoformat(date_start) if date_start else None,
                date_end=date.fromisoformat(date_end) if date_end else None,
                chamber=chamber,
                publication=publication,
                max_decisions=max_decisions,
            )
        logger.info(
            "Worker: Judilibre sync completed — %d fetched, %d new, %d existing, %d errors",
            result.total_fetched, result.new_ingested,
            result.already_exists, result.errors,
        )
    except Exception:
        logger.exception("Worker: Judilibre sync failed")


async def run_kali_install(
    ctx: dict, org_convention_id: str, user_id: str, force_refetch: bool = False,
) -> None:
    """Tâche d'installation d'une convention collective depuis KALI."""
    logger.info("Worker: KALI install started for org_convention %s (force_refetch=%s)", org_convention_id, force_refetch)
    session_factory = ctx["session_factory"]
    try:
        from app.models.ccn import OrganisationConvention
        from app.services.kali_service import KaliService

        service = KaliService()
        async with session_factory() as db:
            org_conv = await db.get(OrganisationConvention, uuid.UUID(org_convention_id))
            if org_conv is None:
                logger.error("OrganisationConvention %s not found", org_convention_id)
                return
            result = await service.install_convention(
                db, org_conv, uuid.UUID(user_id), force_refetch=force_refetch,
            )
        logger.info(
            "Worker: KALI install completed — %d articles, %d docs, %d errors",
            result.articles_count, result.documents_created, result.errors,
        )
    except Exception:
        logger.exception("Worker: KALI install failed for %s", org_convention_id)


async def run_bocc_sync(
    ctx: dict,
    user_id: str,
    *,
    year: int | None = None,
    week: int | None = None,
) -> None:
    """Tâche de synchronisation BOCC."""
    import time as _time
    from datetime import UTC, datetime
    logger.info("Worker: BOCC sync started (year=%s, week=%s)", year, week)
    session_factory = ctx["session_factory"]
    sync_log_id = await _create_sync_log(session_factory, "bocc")
    t0 = _time.perf_counter()
    try:
        from app.models.bocc_issue import BoccIssue
        from app.services.bocc_service import BoccService

        service = BoccService()

        # If no year/week specified, find the latest not yet processed
        if year is None or week is None:
            import datetime as dt
            today = dt.date.today()
            # Current ISO week - 2 (DILA has ~2 week delay)
            target = today - dt.timedelta(weeks=2)
            year = target.isocalendar()[0]
            week = target.isocalendar()[1]

        async with session_factory() as db:
            # Check if already processed
            existing = await db.execute(
                select(BoccIssue).where(BoccIssue.numero == f"{year}-{week:02d}")
            )
            if existing.scalar_one_or_none():
                logger.info("BOCC %d-%02d already processed, skipping", year, week)
                await _finish_sync_log(
                    session_factory, sync_log_id,
                    success=True, items_skipped=1,
                    error_message=f"BOCC {year}-{week:02d} déjà traité",
                    duration_ms=int((_time.perf_counter() - t0) * 1000),
                )
                return

            result = await service.process_issue(db, year, week, uuid.UUID(user_id))

            # Record in bocc_issues
            issue = BoccIssue(
                numero=f"{year}-{week:02d}",
                year=year,
                week=week,
                avenants_count=result.avenants_found,
                avenants_ingested=result.avenants_ingested,
                status="error" if result.errors > 0 and result.avenants_found == 0 else "processed",
                error_message="; ".join(result.error_messages[:3]) if result.error_messages else None,
                processed_at=datetime.now(UTC),
            )
            db.add(issue)
            await db.commit()

        logger.info(
            "Worker: BOCC %d-%02d completed — %d found, %d ingested, %d stored, %d errors",
            year, week, result.avenants_found, result.avenants_ingested,
            result.avenants_stored, result.errors,
        )
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=result.errors == 0 or result.avenants_found > 0,
            items_fetched=result.avenants_found,
            items_created=result.avenants_ingested,
            errors=result.errors,
            error_message="; ".join(result.error_messages[:3]) if result.error_messages else None,
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        logger.exception("Worker: BOCC sync failed")
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=False, errors=1, error_message=str(exc),
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )


async def run_code_travail_sync(ctx: dict, user_id: str) -> None:
    """Tâche de synchronisation du Code du travail."""
    import time as _time
    logger.info("Worker: Code du travail sync started")
    session_factory = ctx["session_factory"]
    sync_log_id = await _create_sync_log(session_factory, "code_travail")
    t0 = _time.perf_counter()
    try:
        from app.services.legi_service import LegiService

        service = LegiService()
        async with session_factory() as db:
            result = await service.sync_code_travail(db, uuid.UUID(user_id))
        logger.info(
            "Worker: Code du travail sync completed — %d législatifs, %d réglementaires, "
            "changed=%s/%s, %d errors",
            result.articles_legislatif, result.articles_reglementaire,
            result.legislatif_changed, result.reglementaire_changed, result.errors,
        )
        changed = result.legislatif_changed or result.reglementaire_changed
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=result.errors == 0,
            items_fetched=result.articles_legislatif + result.articles_reglementaire,
            items_created=1 if changed else 0,
            items_skipped=0 if changed else 1,
            errors=result.errors,
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        logger.exception("Worker: Code du travail sync failed")
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=False, errors=1, error_message=str(exc),
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )


async def run_code_sync(ctx: dict, user_id: str, code_key: str) -> None:
    """Tâche de synchronisation d'un code juridique (civil, pénal, CSS, CASF)."""
    logger.info("Worker: sync %s started", code_key)
    session_factory = ctx["session_factory"]
    try:
        from app.services.legi_service import LegiService

        service = LegiService()
        async with session_factory() as db:
            result = await service.sync_code(db, uuid.UUID(user_id), code_key)
        logger.info(
            "Worker: %s sync completed — %d leg, %d regl, changed=%s/%s, %d errors",
            code_key, result.articles_legislatif, result.articles_reglementaire,
            result.legislatif_changed, result.reglementaire_changed, result.errors,
        )
    except Exception:
        logger.exception("Worker: %s sync failed", code_key)


async def run_all_codes_sync(ctx: dict, user_id: str) -> None:
    """Sync all legal codes (code civil, pénal, CSS, CASF)."""
    import time as _time
    logger.info("Worker: all codes sync started")
    session_factory = ctx["session_factory"]
    sync_log_id = await _create_sync_log(session_factory, "codes")
    t0 = _time.perf_counter()
    total_articles = 0
    total_changed = 0
    total_errors = 0
    try:
        from app.services.legi_service import SYNCABLE_CODES, LegiService

        service = LegiService()
        for code_key in SYNCABLE_CODES:
            if code_key == "code_travail":
                continue  # Already has its own sync
            try:
                async with session_factory() as db:
                    result = await service.sync_code(db, uuid.UUID(user_id), code_key)
                logger.info(
                    "Worker: %s — %d articles, changed=%s, %d errors",
                    code_key, result.articles_legislatif + result.articles_reglementaire,
                    result.legislatif_changed or result.reglementaire_changed,
                    result.errors,
                )
                total_articles += result.articles_legislatif + result.articles_reglementaire
                if result.legislatif_changed or result.reglementaire_changed:
                    total_changed += 1
                total_errors += result.errors
            except Exception:
                logger.exception("Worker: %s sync failed, continuing", code_key)
                total_errors += 1
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=total_errors == 0,
            items_fetched=total_articles,
            items_created=total_changed,
            errors=total_errors,
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        logger.exception("Worker: all codes sync failed")
        await _finish_sync_log(
            session_factory, sync_log_id,
            success=False, errors=1, error_message=str(exc),
            duration_ms=int((_time.perf_counter() - t0) * 1000),
        )


async def run_scheduled_sync(ctx: dict) -> None:
    """Tâche planifiée bimensuelle : sync jurisprudence + rotation CCN."""
    import time as _time

    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.models.ccn import OrganisationConvention
    from app.models.sync_log import SyncLog
    from app.models.user import User

    session_factory = ctx["session_factory"]
    logger.info("Worker: scheduled sync started")

    async with session_factory() as db:
        # Find admin user for ownership of new documents
        admin_result = await db.execute(
            select(User).where(User.role == "admin", User.is_active.is_(True)).limit(1)
        )
        admin = admin_result.scalar_one_or_none()
        if not admin:
            logger.error("No active admin user found — cannot run scheduled sync")
            return
        admin_id = admin.id

        # --- 1. Jurisprudence sync (multi-juridictions) ---
        # Quatre passes successives : Cass. soc + Cass. crim + Cass. com + CA.
        # Chacune écrit son propre SyncLog row avec sync_type='jurisprudence'
        # pour rester groupé sous la même rubrique côté admin.
        from app.services.judilibre_service import JudilibreService

        juris_service = JudilibreService()
        date_end = date.today()
        date_start = date_end - timedelta(days=30)

        # Each entry: (label, sync kwargs)
        jurisprudence_passes = [
            (
                "Cass. soc",
                {
                    "jurisdiction": "cc",
                    "chamber": "soc",
                    "publication": "b",
                    "source_type": "arret_cour_cassation",
                },
            ),
            (
                "Cass. crim",
                {
                    "jurisdiction": "cc",
                    "chamber": "crim",
                    "publication": "b",
                    "source_type": "arret_cour_cassation",
                },
            ),
            (
                "Cass. com",
                {
                    "jurisdiction": "cc",
                    "chamber": "com",
                    "publication": "b",
                    "source_type": "arret_cour_cassation",
                },
            ),
            (
                "Cour d'appel",
                {
                    "jurisdiction": "ca",
                    "publication": "b",
                    "source_type": "arret_cour_appel",
                    "max_decisions": 200,  # cap initial pour CA (volume élevé)
                },
            ),
        ]

        for pass_label, pass_kwargs in jurisprudence_passes:
            t_start = _time.perf_counter()
            sync_log = SyncLog(
                sync_type="jurisprudence",
                status="running",
                started_at=datetime.now(UTC),
            )
            db.add(sync_log)
            await db.commit()
            try:
                result = await juris_service.sync(
                    db=db,
                    user_id=admin_id,
                    date_start=date_start,
                    date_end=date_end,
                    **pass_kwargs,
                )
                duration = int((_time.perf_counter() - t_start) * 1000)
                sync_log.status = "success" if result.errors == 0 else "error"
                sync_log.items_fetched = result.total_fetched
                sync_log.items_created = result.new_ingested
                sync_log.items_skipped = result.already_exists
                sync_log.errors = result.errors
                sync_log.error_message = (
                    "; ".join(result.error_messages[:3])
                    if result.error_messages
                    else None
                )
                sync_log.duration_ms = duration
                sync_log.completed_at = datetime.now(UTC)
                await db.commit()
                logger.info(
                    "Scheduled sync: %s done — %d new, %d skipped, %d errors (%.1fs)",
                    pass_label, result.new_ingested, result.already_exists,
                    result.errors, duration / 1000,
                )
            except Exception as exc:
                sync_log.status = "error"
                sync_log.error_message = str(exc)[:500]
                sync_log.completed_at = datetime.now(UTC)
                sync_log.duration_ms = int((_time.perf_counter() - t_start) * 1000)
                await db.commit()
                logger.exception("Scheduled sync: %s failed", pass_label)

        # --- 2. CCN rotation sync ---
        # Get 10-15 distinct installed CCN, oldest synced first
        ccn_result = await db.execute(
            select(
                OrganisationConvention.idcc,
                func.min(OrganisationConvention.last_synced_at).label("oldest_sync"),
            )
            .where(OrganisationConvention.status.in_(["ready", "error"]))
            .group_by(OrganisationConvention.idcc)
            .order_by(func.min(OrganisationConvention.last_synced_at).nulls_first())
            .limit(15)
        )
        ccn_to_sync = [row[0] for row in ccn_result.all()]

        if ccn_to_sync:
            logger.info(
                "Scheduled sync: %d CCN to check: %s",
                len(ccn_to_sync), ", ".join(ccn_to_sync),
            )
            try:
                from app.services.kali_service import KaliService

                kali = KaliService()
                bulk_result = await kali.bulk_sync_ccn(
                    db=db,
                    idcc_list=ccn_to_sync,
                    user_id=admin_id,
                )

                # Log each CCN result
                for detail in bulk_result.details:
                    ccn_log = SyncLog(
                        sync_type="ccn",
                        idcc=detail.idcc,
                        status="error" if detail.error else ("success" if detail.update_needed else "no_change"),
                        items_fetched=detail.articles_count,
                        items_created=1 if detail.new_document_id else 0,
                        items_updated=0,
                        items_skipped=0 if detail.update_needed else 1,
                        errors=1 if detail.error else 0,
                        error_message=detail.error,
                        started_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                    )
                    db.add(ccn_log)

                await db.commit()
                logger.info(
                    "Scheduled sync: CCN done — %d checked, %d updated, %d unchanged, %d errors",
                    bulk_result.total_idcc, bulk_result.updates_needed,
                    bulk_result.skipped_identical, bulk_result.errors,
                )
            except Exception:
                logger.exception("Scheduled sync: CCN bulk sync failed")
        else:
            logger.info("Scheduled sync: no CCN installed, skipping")

        # --- 3. BOCC weekly sync ---
        bocc_log_id = await _create_sync_log(session_factory, "bocc")
        bocc_t0 = _time.perf_counter()
        try:
            import datetime as dt

            from app.models.bocc_issue import BoccIssue
            from app.services.bocc_service import BoccService

            bocc_service = BoccService()
            # Sync latest available (current week - 2, DILA has ~2 week delay)
            today = dt.date.today()
            target = today - dt.timedelta(weeks=2)
            bocc_year = target.isocalendar()[0]
            bocc_week = target.isocalendar()[1]
            bocc_numero = f"{bocc_year}-{bocc_week:02d}"

            existing_bocc = await db.execute(
                select(BoccIssue).where(BoccIssue.numero == bocc_numero)
            )
            if existing_bocc.scalar_one_or_none():
                logger.info("Scheduled sync: BOCC %s already processed, skipping", bocc_numero)
                await _finish_sync_log(
                    session_factory, bocc_log_id,
                    success=True, items_skipped=1,
                    error_message=f"BOCC {bocc_numero} déjà traité",
                    duration_ms=int((_time.perf_counter() - bocc_t0) * 1000),
                )
            else:
                bocc_result = await bocc_service.process_issue(db, bocc_year, bocc_week, admin_id)
                issue = BoccIssue(
                    numero=bocc_numero,
                    year=bocc_year,
                    week=bocc_week,
                    avenants_count=bocc_result.avenants_found,
                    avenants_ingested=bocc_result.avenants_ingested,
                    status="error" if bocc_result.errors > 0 and bocc_result.avenants_found == 0 else "processed",
                    error_message="; ".join(bocc_result.error_messages[:3]) if bocc_result.error_messages else None,
                    processed_at=datetime.now(UTC),
                )
                db.add(issue)
                await db.commit()
                logger.info(
                    "Scheduled sync: BOCC %s done — %d avenants, %d ingested, %d errors",
                    bocc_numero, bocc_result.avenants_found, bocc_result.avenants_ingested, bocc_result.errors,
                )
                await _finish_sync_log(
                    session_factory, bocc_log_id,
                    success=bocc_result.errors == 0 or bocc_result.avenants_found > 0,
                    items_fetched=bocc_result.avenants_found,
                    items_created=bocc_result.avenants_ingested,
                    errors=bocc_result.errors,
                    error_message="; ".join(bocc_result.error_messages[:3]) if bocc_result.error_messages else None,
                    duration_ms=int((_time.perf_counter() - bocc_t0) * 1000),
                )
        except Exception as exc:
            logger.exception("Scheduled sync: BOCC sync failed")
            await _finish_sync_log(
                session_factory, bocc_log_id,
                success=False, errors=1, error_message=str(exc),
                duration_ms=int((_time.perf_counter() - bocc_t0) * 1000),
            )

        # --- 4. All legal codes sync (Code travail + civil + pénal + CSS + CASF) ---
        # The LegiService computes a SHA-256 of the fetched content and skips
        # ingestion when the hash matches the latest stored version, so this
        # is safe to run on every cron tick — only actual updates cost
        # embeddings. One SyncLog row per code is written so the admin
        # corpus banner can show the status of each code individually.
        try:
            from app.services.legi_service import SYNCABLE_CODES, LegiService

            legi_service = LegiService()
            for code_key, code_def in SYNCABLE_CODES.items():
                # sync_type = "code_travail" for the labour code, "codes" for others
                # so the admin SyncBanner can map them correctly.
                code_log_type = "code_travail" if code_key == "code_travail" else "codes"
                code_log_id = await _create_sync_log(session_factory, code_log_type)
                code_t0 = _time.perf_counter()
                try:
                    result = await legi_service.sync_code(db, code_key=code_key, user_id=admin_id)
                    status = "changed" if (result.legislatif_changed or result.reglementaire_changed) else "unchanged"
                    logger.info(
                        "Scheduled sync: %s — %s (%d articles, %d errors)",
                        code_def["name"], status,
                        result.articles_legislatif + result.articles_reglementaire,
                        result.errors,
                    )
                    changed = result.legislatif_changed or result.reglementaire_changed
                    await _finish_sync_log(
                        session_factory, code_log_id,
                        success=result.errors == 0,
                        items_fetched=result.articles_legislatif + result.articles_reglementaire,
                        items_created=1 if changed else 0,
                        items_skipped=0 if changed else 1,
                        errors=result.errors,
                        duration_ms=int((_time.perf_counter() - code_t0) * 1000),
                    )
                except Exception as exc:
                    logger.exception("Scheduled sync: %s failed, continuing", code_def["name"])
                    await _finish_sync_log(
                        session_factory, code_log_id,
                        success=False, errors=1, error_message=str(exc),
                        duration_ms=int((_time.perf_counter() - code_t0) * 1000),
                    )
        except Exception:
            logger.exception("Scheduled sync: codes sync failed")

    logger.info("Worker: scheduled sync completed")


async def run_bocc_backfill(ctx: dict, user_id: str) -> None:
    """Tâche de backfill complet des BOCC (3 dernières années)."""
    logger.info("Worker: BOCC backfill started")
    session_factory = ctx["session_factory"]
    try:
        from app.services.bocc_service import BoccService

        service = BoccService()
        async with session_factory() as db:
            result = await service.backfill_all(db, uuid.UUID(user_id))
        logger.info(
            "Worker: BOCC backfill completed — %d issues (%d processed, %d skipped), "
            "%d avenants, %d ingested, %d errors",
            result.total_issues, result.issues_processed, result.issues_skipped,
            result.total_avenants, result.total_ingested, result.total_errors,
        )
    except Exception:
        logger.exception("Worker: BOCC backfill failed")


async def run_ccn_blue_green_cleanup(ctx: dict, old_doc_ids: list[str]) -> None:
    """Clean up old CCN documents after blue-green sync (new doc is indexed)."""
    logger.info("Worker: blue-green cleanup for %d old doc(s): %s", len(old_doc_ids), old_doc_ids)
    session_factory = ctx["session_factory"]
    try:
        from app.services.kali_service import KaliService

        async with session_factory() as db:
            cleaned = await KaliService._cleanup_old_ccn_docs(db, old_doc_ids)
        logger.info("Worker: blue-green cleanup completed — %d doc(s) removed", cleaned)
    except Exception:
        logger.exception("Worker: blue-green cleanup failed for docs %s", old_doc_ids)


def _parse_redis_settings() -> RedisSettings:
    """Parse REDIS_URL into ARQ RedisSettings."""
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or 0),
    )


class WorkerSettings:
    functions = [
        run_ingestion,
        run_judilibre_sync,
        run_kali_install,
        run_ccn_blue_green_cleanup,
        run_bocc_sync,
        run_bocc_backfill,
        run_code_travail_sync,
        run_code_sync,
        run_all_codes_sync,
        run_scheduled_sync,
    ]
    # Cron: 1st and 15th of each month at 3:00 AM UTC
    cron_jobs = [
        cron(run_scheduled_sync, month=None, day={1, 15}, hour=3, minute=0),
    ]
    redis_settings = _parse_redis_settings()
    max_jobs = 4
    job_timeout = 14400  # 4h max (BOCC backfill peut prendre plusieurs heures)
    on_startup = on_startup
    on_shutdown = on_shutdown
