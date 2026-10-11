"""Explicit operator import of current Ameli article DOM captures from stdin.

No network fallback or clearance cookies. Keeps automatic failures/report intact.
Run inside the worker image: python -m scripts.maintenance.refresh_ameli_captures
"""

import asyncio
import json
import sys
import time

from sqlalchemy import text

from app.core.database import async_session_factory, engine
from app.services.curated_source_registry import SOURCES
from app.services.curated_source_service import (
    MAX_BYTES,
    CuratedSourceService,
    validate_browser_capture,
)
from app.worker import _create_sync_log, _finish_sync_log


async def main():
    raw = sys.stdin.buffer.read(3 * MAX_BYTES + 1)
    if len(raw) > 3 * MAX_BYTES:
        raise ValueError("Capture bundle exceeds size limit")
    captures = json.loads(raw)
    sources = [s for s in SOURCES if s["key"] in {"N06", "N16", "N17"}]
    if set(captures) != {s["key"] for s in sources}:
        raise ValueError("Exactly the three approved Ameli guides are required")
    for spec in sources:
        validate_browser_capture(spec, captures[spec["key"]])
    async with engine.begin() as lock:
        if not await lock.scalar(text("SELECT pg_try_advisory_xact_lock(20261008, 2)")):
            raise RuntimeError("A curated source synchronization is already running")
        log_id = await _create_sync_log(async_session_factory, "curated_manual")
        start = time.perf_counter()
        try:
            async with async_session_factory() as db:
                result = await CuratedSourceService().sync(db, sources=sources, captures=captures)
            problems = [
                s.get("error", s["status"])
                for s in result["sources"]
                if s["status"] not in {"updated", "unchanged"}
            ]
            await _finish_sync_log(
                async_session_factory,
                log_id,
                success=not problems,
                items_fetched=result["checked"],
                items_updated=result["updated"],
                items_skipped=result["unchanged"],
                errors=result["errors"],
                error_message="; ".join(problems) or None,
                duration_ms=int((time.perf_counter() - start) * 1000),
            )
            print(json.dumps(result, ensure_ascii=False))
            if problems:
                raise SystemExit(1)
        except Exception as exc:
            await _finish_sync_log(
                async_session_factory,
                log_id,
                success=False,
                errors=1,
                error_message=type(exc).__name__,
            )
            raise
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
