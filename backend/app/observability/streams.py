"""Observe protocol outcomes without reading or modifying generated text."""

import asyncio

from app.observability.store import capture


async def observe_stream(stream, request):
    terminal = False
    try:
        async for frame in stream:
            if frame.startswith("event: chat_error\n"):
                terminal = True
                capture("stream_error")
            elif frame.startswith("event: chat_warning\n"):
                capture("stream_warning")
            elif frame.startswith("event: chat_done\n"):
                terminal = True
            yield frame
        if not terminal and not await request.is_disconnected():
            capture("stream_incomplete")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        capture("stream_exception", exception_type=type(exc).__name__)
        raise
    finally:
        await stream.aclose()
