"""Corpus refresh fixes from the Nov. 2026 ingestion audit.

- Codes: an unchanged code is compared with its newest version, and older
  copies left by a missed cleanup are removed (prod had 3 active versions of
  two Codes, ~30 000 extra passages).
- Conventions: old documents are removed once the WHOLE new snapshot is
  indexed, even when a part disappeared or was renamed.
- Dates: passages carry the document's official date, never a date guessed
  from their text.
- KALI install: a new request is not silently dropped after a previous run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.models.document import Document
from app.rag.ingestion import document_content_date
from app.services import legi_service as legi_module
from app.services.kali_service import KaliService
from app.services.legi_service import LegiService
from tests.conftest import test_session_factory as session_factory


def _code_doc(file_hash: str, age_days: int, status: str = "indexed") -> Document:
    return Document(
        name="Code général des impôts — Partie législative",
        source_type="code_general_impots",
        storage_path=f"common/codes/{uuid.uuid4()}.txt",
        file_hash=file_hash,
        indexation_status=status,
        chunk_count=10,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


async def _sync_code(monkeypatch, articles_hash: str):
    service = LegiService()
    monkeypatch.setattr(service, "_format_articles_as_markdown", lambda articles, name: "texte")
    monkeypatch.setattr(
        legi_module.hashlib,
        "sha256",
        lambda data: SimpleNamespace(hexdigest=lambda: articles_hash),
    )
    monkeypatch.setattr(legi_module, "enqueue_ingestion", AsyncMock())
    cleanup = AsyncMock()
    monkeypatch.setattr(KaliService, "_enqueue_old_docs_cleanup", cleanup)
    async with session_factory() as db:
        changed, new_id = await service._sync_part(
            db,
            [],
            "code_general_impots",
            "Code général des impôts — Partie législative",
            uuid.uuid4(),
            Mock(),
        )
    return changed, new_id, cleanup


async def test_unchanged_code_removes_older_copies_instead_of_adding_one(monkeypatch):
    async with session_factory() as db:
        older = [_code_doc("v1", 26), _code_doc("v2", 19)]
        current = _code_doc("v3", 5)
        db.add_all([*older, current])
        await db.commit()
        older_ids = sorted(str(d.id) for d in older)

    changed, new_id, cleanup = await _sync_code(monkeypatch, "v3")

    assert (changed, new_id) == (False, None)
    cleanup.assert_awaited_once()
    assert sorted(cleanup.await_args.args[0]) == older_ids


async def test_code_version_that_failed_to_index_is_rebuilt(monkeypatch):
    async with session_factory() as db:
        db.add(_code_doc("v3", 5, status="error"))
        await db.commit()

    changed, new_id, cleanup = await _sync_code(monkeypatch, "v3")

    assert changed and new_id
    cleanup.assert_awaited_once()


def _qdrant(counts: dict[str, int], fail_delete: bool = False) -> Mock:
    qdrant = Mock()

    def count(_collection, count_filter, exact):
        doc_id = count_filter.must[0].match.value
        return SimpleNamespace(count=counts.get(doc_id, 0))

    qdrant.count.side_effect = count
    if fail_delete:
        qdrant.delete.side_effect = RuntimeError("qdrant down")
    return qdrant


async def _snapshot(monkeypatch, *, new_status="indexed", indexed_points=4, fail_delete=False):
    async with session_factory() as db:
        old = Document(
            name="CCN X (IDCC 0413) — Grilles de salaires",  # part gone from KALI
            source_type="convention_collective_nationale",
            storage_path="common/ccn/0413/old.txt",
            indexation_status="indexed",
            chunk_count=2,
        )
        new = Document(
            name="CCN X (IDCC 0413)",
            source_type="convention_collective_nationale",
            storage_path="common/ccn/0413/new.txt",
            indexation_status=new_status,
            chunk_count=4,
        )
        db.add_all([old, new])
        await db.commit()
        old_id, new_id = str(old.id), str(new.id)
    qdrant = _qdrant({new_id: indexed_points}, fail_delete=fail_delete)
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: Mock())
    async with session_factory() as db:
        cleaned = await KaliService._cleanup_old_ccn_docs(db, [old_id], [new_id])
    async with session_factory() as db:
        old_left = await db.get(Document, uuid.UUID(old_id))
    return cleaned, old_left


async def test_old_part_without_same_name_replacement_is_removed(monkeypatch):
    cleaned, old_left = await _snapshot(monkeypatch)
    assert cleaned == 1 and old_left is None


async def test_old_snapshot_kept_while_new_one_is_incomplete(monkeypatch):
    cleaned, old_left = await _snapshot(monkeypatch, new_status="indexing")
    assert cleaned == 0 and old_left is not None
    cleaned, old_left = await _snapshot(monkeypatch, indexed_points=3)
    assert cleaned == 0 and old_left is not None


async def test_document_row_kept_when_vectors_cannot_be_deleted(monkeypatch):
    cleaned, old_left = await _snapshot(monkeypatch, fail_delete=True)
    assert cleaned == 0 and old_left is not None


def test_content_date_comes_from_official_metadata_only():
    doc = Document(name="x", source_type="decret")
    assert document_content_date(doc) is None
    doc.date_decision = date(2025, 1, 2)
    doc.source_updated_date = date(2025, 6, 1)
    assert document_content_date(doc) == "2025-06-01"
    doc.publication_date = date(2026, 11, 3)
    assert document_content_date(doc) == "2026-11-03"


def test_kali_install_job_keeps_no_result():
    from app.worker import WorkerSettings

    job = next(
        f
        for f in WorkerSettings.functions
        if getattr(f, "name", getattr(f, "__name__", "")) == "run_kali_install"
    )
    assert job.keep_result_s == 0
