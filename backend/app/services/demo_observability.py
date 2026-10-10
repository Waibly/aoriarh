"""Observe uniquement les événements techniques SSE, jamais leur contenu éditorial."""

import asyncio
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import Request

logger = structlog.get_logger(__name__)


async def observe_demo_stream(
    stream: AsyncGenerator[str, None],
    request: Request,
) -> AsyncGenerator[str, None]:
    terminal = False
    logger.info("demo_stream_started")
    try:
        async for frame in stream:
            if frame.startswith("event: chat_error\n"):
                terminal = True
                logger.error("demo_stream_failed")
            elif frame.startswith("event: chat_done\n"):
                terminal = True
                logger.info("demo_stream_completed")
            yield frame
    except asyncio.CancelledError:
        logger.info("demo_stream_disconnected")
        raise
    except Exception:
        # Le détail technique reste dans les logs serveur ; aucun contenu utilisateur.
        logger.error("demo_stream_failed", reason="unhandled_exception")
        terminal = True
        yield (
            "event: chat_error\ndata: "
            + json.dumps(
                {
                    "error": "server_error",
                    "message": "La démonstration a rencontré une erreur technique.",
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
    finally:
        await stream.aclose()
    if not terminal:
        if await request.is_disconnected():
            logger.info("demo_stream_disconnected")
        else:
            logger.error("demo_stream_failed", reason="missing_completion")
            yield (
                "event: chat_error\ndata: "
                + json.dumps(
                    {
                        "error": "incomplete_stream",
                        "message": "La réponse a été interrompue.",
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            )
