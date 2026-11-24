"""Hand an answer to the worker for review, without ever touching the chat response."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


async def _enqueue(message_id: str) -> None:
    try:
        from app.core.database import async_session_factory
        from app.services.platform_settings import get_quality_review_settings

        async with async_session_factory() as db:
            config = await get_quality_review_settings(db)
        if config.mode == "off":
            return
        from app.rag.tasks import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_quality_review", message_id, _job_id=f"quality_review:{message_id}"
        )
    except Exception:
        logger.exception("Quality review could not be scheduled for answer %s", message_id)


def schedule_quality_review(message_id: str) -> None:
    """Fire and forget: returns at once; any failure is only logged."""
    try:
        task = asyncio.get_running_loop().create_task(_enqueue(message_id))
    except RuntimeError:
        return
    _background.add(task)
    task.add_done_callback(_background.discard)
