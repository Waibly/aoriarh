import logging

from arq.connections import ArqRedis, create_pool

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def _parse_redis_settings():
    from urllib.parse import urlparse

    from arq.connections import RedisSettings

    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or 0),
    )


async def get_arq_pool() -> ArqRedis:
    """Return a shared ARQ connection pool (lazy singleton)."""
    global _pool
    if _pool is None:
        _pool = await create_pool(_parse_redis_settings())
    return _pool


async def enqueue_ingestion(document_id: str) -> None:
    """Enqueue a document ingestion job to the ARQ worker."""
    pool = await get_arq_pool()
    await pool.enqueue_job("run_ingestion", document_id)
    logger.info("Ingestion job enqueued for document %s", document_id)


async def enqueue_judilibre_sync(
    user_id: str,
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    chamber: str = "soc",
    publication: str = "b",
    max_decisions: int | None = None,
) -> None:
    """Enqueue a Judilibre sync job to the ARQ worker."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_judilibre_sync",
        user_id,
        date_start=date_start,
        date_end=date_end,
        chamber=chamber,
        publication=publication,
        max_decisions=max_decisions,
        _job_id="judilibre_sync",  # single job — prevent duplicates
    )
    logger.info("Judilibre sync job enqueued")
