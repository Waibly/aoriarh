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
    functions = [run_ingestion, run_judilibre_sync]
    redis_settings = _parse_redis_settings()
    max_jobs = 4
    job_timeout = 1800  # 30 min max par ingestion (gros PDFs comme le Code du travail)
    on_startup = on_startup
    on_shutdown = on_shutdown
