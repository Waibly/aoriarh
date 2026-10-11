"""Technical corpus counters and sync outcomes (no content evaluation)."""
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.api.admin_corpus import get_corpus_health
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.worker import _finish_sync_log
from tests.conftest import test_session_factory as session_factory


@pytest.mark.asyncio
async def test_retired_documents_do_not_keep_corpus_busy(client, admin_user):
    async with session_factory() as db:
        for state, retired in [("pending", True), ("indexing", True), ("indexed", False)]:
            db.add(Document(
                name=state, source_type="arret_cour_appel", storage_path="test/" + state,
                indexation_status=state, retired_at=datetime.now(UTC) if retired else None,
            ))
        await db.commit()
        health = await get_corpus_health(user=None, db=db)
    assert health.common_total == health.indexed_count == 1
    assert health.pending_count == health.indexing_count == 0
    assert not health.is_busy
    headers = {"Authorization": "Bearer " + admin_user["token"]}
    groups = await client.get("/api/v1/admin/documents/groups", headers=headers)
    assert groups.status_code == 200
    assert groups.json()["total"] == 1
    listing = await client.get("/api/v1/admin/documents/groups/arret_cour_appel", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("success,errors,expected,alert", [
    (True, 0, "deferred", False),
    (False, 1, "error", True),
    (True, 1, "error", True),
])
async def test_quota_deferral_is_not_a_failure_but_real_errors_still_alert(
    success, errors, expected, alert,
):
    async with session_factory() as db:
        row = SyncLog(sync_type="social_ca", status="running", started_at=datetime.now(UTC))
        db.add(row)
        await db.commit()
        log_id = row.id
    with patch("app.observability.store.capture") as capture:
        await _finish_sync_log(session_factory, str(log_id), success=success,
                               deferred=True, errors=errors, items_created=20,
                               error_message="97 décisions reportées")
    assert capture.called is alert
    async with session_factory() as db:
        saved = await db.get(SyncLog, log_id)
        assert saved.status == expected
        assert saved.items_created == 20
        assert saved.completed_at is not None


@pytest.mark.asyncio
async def test_multiple_running_syncs_return_conflict_not_server_error(client, admin_user):
    async with session_factory() as db:
        db.add_all([
            SyncLog(sync_type="jurisprudence", status="running", started_at=datetime.now(UTC))
            for _ in range(2)
        ])
        await db.commit()
    response = await client.post(
        "/api/v1/admin/syncs/trigger",
        headers={"Authorization": "Bearer " + admin_user["token"]},
    )
    assert response.status_code == 409
