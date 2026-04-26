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


async def enqueue_kali_install(
    org_convention_id: str, user_id: str, force_refetch: bool = False,
) -> None:
    """Enqueue a KALI convention installation job to the ARQ worker."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_kali_install",
        org_convention_id,
        user_id,
        force_refetch,
        _job_id=f"kali_install_{org_convention_id}",
    )
    logger.info("KALI install job enqueued for org_convention %s (force_refetch=%s)", org_convention_id, force_refetch)


async def enqueue_bocc_sync(user_id: str, year: int | None = None, week: int | None = None) -> None:
    """Enqueue a BOCC sync job. If year/week not specified, syncs latest."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_bocc_sync",
        user_id,
        year=year,
        week=week,
    )
    logger.info("BOCC sync job enqueued (year=%s, week=%s)", year, week)


async def enqueue_bocc_backfill(user_id: str) -> None:
    """Enqueue a full BOCC backfill job (3 last years)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_bocc_backfill",
        user_id,
    )
    logger.info("BOCC backfill job enqueued")


async def enqueue_code_travail_sync(user_id: str) -> None:
    """Enqueue a Code du travail sync job."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_code_travail_sync",
        user_id,
    )
    logger.info("Code du travail sync job enqueued")


async def enqueue_all_codes_sync(user_id: str) -> None:
    """Enqueue sync for all legal codes (civil, pénal, CSS, CASF)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_all_codes_sync",
        user_id,
    )
    logger.info("All codes sync job enqueued")


async def enqueue_scheduled_sync() -> None:
    """Enqueue the bi-monthly scheduled sync (jurisprudence + CCN rotation)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_scheduled_sync",
    )
    logger.info("Scheduled sync job enqueued")


async def enqueue_judilibre_sync(
    user_id: str,
    *,
    date_start: str | None = None,
    date_end: str | None = None,
    chamber: str = "soc",
    publication: str = "b",
    max_decisions: int | None = None,
) -> None:
    """Enqueue a Judilibre sync job to the ARQ worker (single chamber/jurisdiction)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_judilibre_sync",
        user_id,
        date_start=date_start,
        date_end=date_end,
        chamber=chamber,
        publication=publication,
        max_decisions=max_decisions,
    )
    logger.info("Judilibre sync job enqueued")


async def enqueue_full_jurisprudence_sync(user_id: str) -> None:
    """Enqueue a FULL jurisprudence sync : Cass soc/cr/comm/civ2 + CA soc + Conseil constit (30j)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_full_jurisprudence_sync",
        user_id,
    )
    logger.info("Full jurisprudence sync job enqueued")


async def enqueue_custom_jurisprudence_sync(
    user_id: str,
    *,
    source: str,
    date_start: str,
    date_end: str,
    max_decisions: int | None = None,
) -> None:
    """Enqueue une sync jurisprudence personnalisée (source + plage de dates choisies)."""
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_custom_jurisprudence_sync",
        user_id,
        source=source,
        date_start=date_start,
        date_end=date_end,
        max_decisions=max_decisions,
    )
    logger.info(
        "Custom jurisprudence sync enqueued: source=%s, %s → %s, cap=%s",
        source, date_start, date_end, max_decisions,
    )


async def enqueue_jurisprudence_initialization(user_id: str) -> None:
    """Enqueue ONE-SHOT initialization of jurisprudence corpus.

    Cass passes on 1 year publié + CA chambre sociale on 3 months capped
    at 3000. To be triggered manually from the admin Corpus page only
    once at deployment time. Idempotent thanks to numero_pourvoi dedup.
    """
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_jurisprudence_initialization",
        user_id,
    )
    logger.info("Jurisprudence initialization job enqueued")
