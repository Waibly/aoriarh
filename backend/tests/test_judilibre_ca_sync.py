"""Technical collection/identity/checkpoint contracts; no generation evaluation."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from app.models.document import Document
from app.models.judilibre import JudilibreRecord, JudilibreScan, JudilibreScanItem
from app.models.sync_log import SyncLog
from app.services.judilibre_ca_sync import (
    IncompleteScanError,
    JudilibreCaCollector,
    dispatch_indexing,
    finish_scans,
    next_cursor,
    record_scan_failure,
    schedule_recurring,
    schedule_scan,
)
from app.services.judilibre_service import JudilibreService
from tests.conftest import test_session_factory as session_factory


def decision(number=1, **overrides):
    return {
        "id": f"{number:024x}",
        "jurisdiction": "ca",
        "location": "ca_paris",
        "number": "25/13232",
        "chamber": "Pôle 1 - Chambre 2",
        "nac": "78K",
        "decision_date": "2026-05-21",
        "update_date": "2026-05-30",
        "text": "Texte officiel intégral.\n\nFin.\n",
        **overrides,
    }


@pytest.fixture
def collector():
    api = JudilibreService()
    api._api_get = AsyncMock()
    return JudilibreCaCollector(api=api, storage=MagicMock())


async def scan(db, key="test"):
    s = await schedule_scan(db, key=key, start=date(2026, 1, 1), end=date(2026, 10, 4))
    await db.commit()
    return s


async def test_all_chambers_and_exact_source_identity(collector):
    async with session_factory() as db:
        for raw in [
            decision(),
            decision(2, location="ca_lyon"),
            decision(3, decision_date="2026-05-22"),
        ]:
            assert await collector.upsert(db, raw) == "created"
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(Document)) == 3
        assert await collector.upsert(db, decision()) == "existing"
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(Document)) == 3
        d = await db.scalar(select(Document).where(Document.source_url.endswith(f"{1:024x}")))
        assert d.source_updated_date == date(2026, 5, 30)
        assert d.organisation_id is None
        collector.storage.put_file_bytes.assert_any_call(
            d.storage_path, decision()["text"].encode(), content_type="text/plain"
        )


async def test_update_reuses_identity_and_pins_new_immutable_source(collector):
    async with session_factory() as db:
        await collector.upsert(db, decision())
        await db.commit()
        record = await db.get(JudilibreRecord, f"{1:024x}")
        d = await db.get(Document, record.document_id)
        old_path = d.storage_path
        d.indexation_status = "indexed"
        record.needs_indexing, record.enqueue_attempts = False, 3
        await db.commit()
        assert (
            await collector.upsert(
                db, decision(text="Nouvelle version\n", update_date="2026-10-08")
            )
            == "updated"
        )
        await db.commit()
        assert d.storage_path != old_path
        assert d.indexation_status == "pending"
        assert record.needs_indexing and record.enqueue_attempts == 0
        assert await db.scalar(select(func.count()).select_from(Document)) == 1


async def test_adopts_only_exact_legacy_document(collector):
    async with session_factory() as db:
        await collector.upsert(db, decision())
        await db.commit()
        record = await db.get(JudilibreRecord, f"{1:024x}")
        doc = await db.get(Document, record.document_id)
        original_id = doc.id
        await db.delete(record)
        doc.source_url, doc.indexation_status = None, "indexed"
        await db.commit()
        assert await collector.upsert(db, decision()) == "existing"
        await db.commit()
        record = await db.get(JudilibreRecord, f"{1:024x}")
        assert record.document_id == original_id
        assert not record.needs_indexing


@pytest.mark.parametrize(
    "changes", [{"text": ""}, {"decision_date": "invalid"}, {"id": "bad"}, {"jurisdiction": "cc"}]
)
async def test_invalid_source_is_technical_error(collector, changes):
    async with session_factory() as db:
        with pytest.raises(ValueError):
            await collector.upsert(db, decision(**changes))
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(Document)) == 0


async def test_cursor_survives_new_session_and_completion_waits_for_indexing(collector):
    collector.api._api_get.side_effect = [
        {
            "total": 2,
            "results": [decision()],
            "next_batch": "jurisdiction=ca&searchAfter=0%26date%26id",
        },
        {"total": 2, "results": [decision(2)], "next_batch": None},
    ]
    async with session_factory() as db:
        s = await scan(db)
        sid = s.id
        await collector.page(db, s, None)
        assert s.cursor == "0&date&id" and s.status == "pending"
    async with session_factory() as db:
        s = await db.get(JudilibreScan, sid)
        await collector.page(db, s, None)
        assert collector.api._api_get.call_args.kwargs["params"]["searchAfter"] == "0&date&id"
        assert s.status == "awaiting_index"
        await finish_scans(db)
        assert (await db.get(SyncLog, s.sync_log_id)).status == "running"
        for d in (await db.scalars(select(Document))).all():
            d.indexation_status = "indexed"
        await db.commit()
        await finish_scans(db)
        assert s.status == "complete"
        assert (await db.get(SyncLog, s.sync_log_id)).status == "success"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"total": 2, "results": [decision()], "next_batch": None},
        {"total": 2, "results": [], "next_batch": "searchAfter=same"},
    ],
)
async def test_incomplete_or_failed_page_never_advances(collector, response):
    collector.api._api_get.return_value = response
    async with session_factory() as db:
        s = await scan(db)
        sid = s.id
        with pytest.raises(RuntimeError) as error:
            await collector.page(db, s, None)
        await record_scan_failure(db, sid, error.value)
        s = await db.get(JudilibreScan, sid)
        assert s.cursor is None and s.status != "complete"
        assert await db.scalar(select(func.count()).select_from(JudilibreScanItem)) == 0
        assert await db.scalar(select(func.count()).select_from(Document)) == 0


async def test_duplicate_page_and_changed_total_force_bounded_restart(collector):
    async with session_factory() as db:
        s = await scan(db)
        sid = s.id
        collector.api._api_get.return_value = {
            "total": 2,
            "results": [decision()],
            "next_batch": "searchAfter=a",
        }
        await collector.page(db, s, None)
        collector.api._api_get.return_value = {
            "total": 2,
            "results": [decision()],
            "next_batch": "searchAfter=b",
        }
        with pytest.raises(IncompleteScanError):
            await collector.page(db, s, None)
        await record_scan_failure(db, sid, IncompleteScanError("duplicate"))
        for _ in range(2):
            await record_scan_failure(db, sid, IncompleteScanError("changed inventory"))
        s = await db.get(JudilibreScan, sid)
        assert s.status == "error" and s.attempts == 3 and s.cursor is None
        # Earlier committed data is retained and will deduplicate by source ID.
        assert await db.scalar(select(func.count()).select_from(Document)) == 1


async def test_enqueue_failure_preserves_outbox_and_pins_source(collector):
    async with session_factory() as db:
        await collector.upsert(db, decision())
        await db.commit()
        pool = MagicMock()
        pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis unavailable"))
        now = datetime.now(UTC)
        with pytest.raises(RuntimeError):
            await dispatch_indexing(db, pool, now)
        await db.rollback()
        record = await db.get(JudilibreRecord, f"{1:024x}")
        assert record.needs_indexing and record.enqueue_attempts == 0
        pool.enqueue_job.side_effect = None
        await dispatch_indexing(db, pool, now)
        d = await db.get(Document, record.document_id)
        assert pool.enqueue_job.call_args.kwargs["expected_source"] == d.storage_path
        assert record.enqueue_attempts == 1
        await dispatch_indexing(db, pool, now + timedelta(minutes=1))
        assert record.enqueue_attempts == 1


async def test_lost_indexing_jobs_stop_after_three_technical_submissions(collector):
    async with session_factory() as db:
        await collector.upsert(db, decision())
        await db.commit()
        pool = MagicMock()
        pool.enqueue_job = AsyncMock()
        now = datetime.now(UTC)
        for i in range(4):
            await dispatch_indexing(db, pool, now + timedelta(hours=5 * i))
        assert pool.enqueue_job.await_count == 3
        d = await db.scalar(select(Document))
        assert d.indexation_status == "error"


async def test_scheduler_recovers_downtime_and_does_not_duplicate_history():
    async with session_factory() as db:
        await schedule_recurring(db, date(2026, 10, 8))
        await schedule_recurring(db, date(2026, 10, 8))
        history = (
            await db.scalars(
                select(JudilibreScan)
                .where(JudilibreScan.date_type == "creation")
                .order_by(JudilibreScan.date_start)
            )
        ).all()
        assert history[0].date_start == date(2026, 1, 1)
        assert history[-1].date_end == date(2026, 10, 7)
        for previous, following in zip(history, history[1:]):
            assert previous.date_end + timedelta(days=1) == following.date_start
            assert (previous.date_end - previous.date_start).days == 6
        assert await db.scalar(select(func.count()).select_from(JudilibreScan)) == len(history) + 1
        await schedule_recurring(db, date(2026, 10, 20))
        s = await db.scalar(
            select(JudilibreScan).where(JudilibreScan.key == "ca:updates:2026-10-19")
        )
        assert s.date_start == date(2026, 10, 5)
        assert s.date_type == "update"
        assert await db.scalar(select(func.count()).select_from(JudilibreScan)) == len(history) + 2


def test_cursor_extracts_only_opaque_token():
    assert next_cursor("https://untrusted.invalid/scan?searchAfter=0%26x%26id") == "0&x&id"
    assert next_cursor(None) is None
    with pytest.raises(IncompleteScanError):
        next_cursor("searchAfter=a&searchAfter=b")
