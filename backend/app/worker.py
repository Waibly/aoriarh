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


async def run_kali_install(ctx: dict, org_convention_id: str, user_id: str) -> None:
    """Tâche d'installation d'une convention collective depuis KALI."""
    logger.info("Worker: KALI install started for org_convention %s", org_convention_id)
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
            result = await service.install_convention(db, org_conv, uuid.UUID(user_id))
        logger.info(
            "Worker: KALI install completed — %d articles, %d docs, %d errors",
            result.articles_count, result.documents_created, result.errors,
        )
    except Exception:
        logger.exception("Worker: KALI install failed for %s", org_convention_id)


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

        # --- 1. Jurisprudence sync ---
        t_start = _time.perf_counter()
        started_at = datetime.now(UTC)
        sync_log = SyncLog(
            sync_type="jurisprudence",
            status="running",
            started_at=started_at,
        )
        db.add(sync_log)
        await db.commit()

        try:
            from app.services.judilibre_service import JudilibreService

            service = JudilibreService()
            # Sync last 30 days only (incremental)
            date_end = date.today()
            date_start = date_end - timedelta(days=30)
            result = await service.sync(
                db=db,
                user_id=admin_id,
                date_start=date_start,
                date_end=date_end,
                chamber="soc",
                publication="b",
            )
            duration = int((_time.perf_counter() - t_start) * 1000)
            sync_log.status = "success" if result.errors == 0 else "error"
            sync_log.items_fetched = result.total_fetched
            sync_log.items_created = result.new_ingested
            sync_log.items_skipped = result.already_exists
            sync_log.errors = result.errors
            sync_log.error_message = "; ".join(result.error_messages[:3]) if result.error_messages else None
            sync_log.duration_ms = duration
            sync_log.completed_at = datetime.now(UTC)
            await db.commit()

            logger.info(
                "Scheduled sync: jurisprudence done — %d new, %d skipped, %d errors (%.1fs)",
                result.new_ingested, result.already_exists, result.errors, duration / 1000,
            )
        except Exception as exc:
            sync_log.status = "error"
            sync_log.error_message = str(exc)[:500]
            sync_log.completed_at = datetime.now(UTC)
            sync_log.duration_ms = int((_time.perf_counter() - t_start) * 1000)
            await db.commit()
            logger.exception("Scheduled sync: jurisprudence failed")

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

    logger.info("Worker: scheduled sync completed")


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
        run_scheduled_sync,
    ]
    # Cron: 1st and 15th of each month at 3:00 AM UTC
    cron_jobs = [
        cron(run_scheduled_sync, month=None, day={1, 15}, hour=3, minute=0),
    ]
    redis_settings = _parse_redis_settings()
    max_jobs = 4
    job_timeout = 1800  # 30 min max par ingestion (gros PDFs comme le Code du travail)
    on_startup = on_startup
    on_shutdown = on_shutdown
