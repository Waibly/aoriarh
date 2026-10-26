import hashlib
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.document import Document
from app.services.judilibre_source_maintenance import refresh_judilibre_source
from tests.conftest import test_session_factory


@pytest.fixture
async def source(monkeypatch):
    body = "Texte original, sans modification.\n"
    raw = {"number": "26-12.345", "decision_date": "2026-10-20", "text": body,
           "summary": "Premier sommaire officiel.", "titlesAndSummaries": [
               {"summary": "Second sommaire officiel.", "titles": ["Titre officiel"]},
           ]}
    doc = Document(name="Source publique", source_type="arret_cour_cassation",
                   storage_path="common/judilibre/original.txt", numero_pourvoi=raw["number"],
                   date_decision=date(2026, 10, 20),
                   file_hash=hashlib.sha256(body.encode()).hexdigest(),
                   source_url="https://www.courdecassation.fr/decision/official-id",
                   indexation_status="indexed")
    blobs = {doc.storage_path: body.encode()}
    storage = Mock()
    storage.get_file_bytes.side_effect = lambda path: blobs[path]
    storage.put_file_bytes.side_effect = lambda path, data, **kw: blobs.__setitem__(path, data)
    service = SimpleNamespace(_api_get=AsyncMock(return_value=raw))
    queue = AsyncMock()
    monkeypatch.setattr("app.services.judilibre_source_maintenance.enqueue_ingestion", queue)
    async with test_session_factory() as db:
        db.add(doc)
        await db.commit()
        yield SimpleNamespace(db=db, doc=doc, blobs=blobs, storage=storage, service=service,
                              raw=raw, queue=queue)


async def test_report_does_not_change_document_storage_or_queue(source):
    result = await refresh_judilibre_source(source.db, source.doc.id,
                                           service=source.service, storage=source.storage)
    assert result["official_summaries"] == 2
    assert result["changed"] and not result["applied"]
    assert source.doc.storage_path == "common/judilibre/original.txt"
    source.storage.put_file_bytes.assert_not_called()
    source.queue.assert_not_awaited()


async def test_apply_preserves_body_raw_api_and_identity_and_is_repeatable(source):
    original_id = source.doc.id
    result = await refresh_judilibre_source(source.db, original_id, apply=True,
                                           service=source.service, storage=source.storage)
    assert result["applied"]
    assert source.doc.id == original_id
    path = source.doc.storage_path
    assert path != "common/judilibre/original.txt"
    assert source.blobs[path].endswith(source.raw["text"].encode())
    assert source.blobs["common/judilibre/original.txt"] == source.raw["text"].encode()
    import json
    assert json.loads(source.blobs[path + ".source.json"]) == source.raw
    source.queue.assert_awaited_once_with(str(original_id), expected_source=path)
    source.storage.put_file_bytes.reset_mock()
    result = await refresh_judilibre_source(source.db, original_id, apply=True,
                                           service=source.service, storage=source.storage)
    assert not result["changed"] and not result["applied"]
    source.storage.put_file_bytes.assert_not_called()


async def test_changed_official_body_is_reported_without_overwriting(source):
    source.raw["text"] = "Autre version du corps."
    with pytest.raises(ValueError, match="body_changed_requires_review"):
        await refresh_judilibre_source(source.db, source.doc.id, apply=True,
                                       service=source.service, storage=source.storage)
    source.storage.put_file_bytes.assert_not_called()
    source.queue.assert_not_awaited()


async def test_identity_mismatch_never_replaces_source(source):
    source.raw["number"] = "26-99.999"
    with pytest.raises(ValueError, match="identity_mismatch"):
        await refresh_judilibre_source(source.db, source.doc.id, apply=True,
                                       service=source.service, storage=source.storage)
    source.storage.put_file_bytes.assert_not_called()


async def test_private_sources_are_outside_maintenance_scope(source):
    source.doc.private_conversation_id = uuid.uuid4()
    await source.db.commit()
    with pytest.raises(ValueError, match="outside_public_scope"):
        await refresh_judilibre_source(source.db, source.doc.id, apply=True,
                                       service=source.service, storage=source.storage)
    source.service._api_get.assert_not_awaited()
    source.storage.get_file_bytes.assert_not_called()
