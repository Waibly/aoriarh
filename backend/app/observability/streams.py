"""Observe protocol outcomes without reading or modifying generated text."""

import asyncio
import json

from app.observability.store import capture


async def observe_stream(stream, request):
    terminal = False
    try:
        async for frame in stream:
            if frame.startswith("event: chat_error\n"):
                terminal = True
                # Read only the protocol error code, never generated content or messages.
                reason = None
                try:
                    data = json.loads("\n".join(
                        line[6:] for line in frame.splitlines() if line.startswith("data: ")
                    ))
                    if isinstance(data, dict) and data.get("error") in (
                        "provider_quota_exhausted", "provider_rate_limited", "server_error"
                    ):
                        reason = data["error"]
                except (ValueError, TypeError):
                    pass
                capture("stream_error", reason=reason)
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
