"""Versioned extraction pilot: actual DB/HTTP, fake object storage, no paid APIs."""

import hashlib
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select, update
from starlette.datastructures import Headers

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.main import app
from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.rag.ingestion import IngestionPipeline
from app.rag.text_extractor import TextExtractor
from app.services.document_extraction_service import (
    DocumentExtractionService,
    ExtractionError,
    SourceSnapshot,
)
from app.services.document_service import DocumentService
from app.services.storage_service import StorageService
from tests.conftest import test_session_factory

RAW = "  Pièce originale\n\nTrain : 84 €\n<script>alert(1)</script>  "


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.reads = []
        self.puts = []

    def put_file_bytes(self, path, data, content_type):
        self.puts.append(path)
        self.objects[path] = data

    def get_file_bytes(self, path):
        return self.objects[path]

    def get_file_bytes_bounded(self, path, max_bytes):
        self.reads.append(path)
        data = self.objects[path]
        if len(data) > max_bytes:
            raise ValueError("read_budget_exceeded")
        return data

    def delete_file(self, path):
        self.objects.pop(path, None)


@pytest.fixture
async def dossier(monkeypatch):
    async with test_session_factory() as db:
        user = User(id=uuid.uuid4(), email="reader@example.test", full_name="Reader", role="user")
        org = Organisation(id=uuid.uuid4(), name="Org A")
        other_org = Organisation(id=uuid.uuid4(), name="Org B")
        db.add_all([user, org, other_org])
        await db.flush()
        db.add(Membership(user_id=user.id, organisation_id=org.id, role_in_org="user"))
        doc = Document(
            id=uuid.uuid4(),
            organisation_id=org.id,
            name="divers.txt",
            source_type="divers",
            storage_path=f"{org.id}/original.txt",
            file_hash=hashlib.sha256(RAW.encode()).hexdigest(),
            file_format="txt",
        )
        db.add(doc)
        await db.commit()
        storage = MemoryStorage()
        storage.objects[doc.storage_path] = RAW.encode()
        service = DocumentExtractionService(db, storage)
        yield SimpleNamespace(
            db=db,
            user=user,
            org=org,
            other_org=other_org,
            doc=doc,
            storage=storage,
            service=service,
        )


async def prepare(dossier):
    text = await dossier.service.extract(
        SourceSnapshot.from_document(dossier.doc), RAW.encode(), TextExtractor()
    )
    assert text == RAW
    return await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)


async def read(dossier, manifest, max_bytes=24_000):
    return await dossier.service.read(
        dossier.doc.id, dossier.org.id, dossier.user.id, manifest["extraction_id"], max_bytes
    )


async def test_exact_raw_text_is_persisted_and_read_without_rag(dossier):
    manifest = await prepare(dossier)
    result = await read(dossier, manifest)
    assert result["text"] == RAW
    assert result["text_sha256"] == hashlib.sha256(RAW.encode()).hexdigest()
    assert result["text_bytes"] == len(RAW.encode())
    assert result["coverage"]["file_completeness"] == "not_certified"
    assert "storage_path" not in repr(result)
    assert dossier.doc.indexation_status == "pending"  # Readiness != indexed.


async def test_successful_extraction_is_reused_without_reextracting(dossier):
    first = await prepare(dossier)
    extractor = MagicMock()
    extractor.extract.side_effect = AssertionError("must not reextract")
    result = await dossier.service.extract(
        SourceSnapshot.from_document(dossier.doc), RAW.encode(), extractor
    )
    assert result == RAW
    second = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    assert first["extraction_id"] == second["extraction_id"]
    assert len(dossier.storage.puts) == 1


@pytest.mark.parametrize("kind", ["foreign_org", "revoked", "inactive", "deleted", "common"])
async def test_current_acl_checked_before_any_storage_read(dossier, kind):
    manifest = await prepare(dossier)
    if kind == "foreign_org":
        org_id = dossier.other_org.id
    else:
        org_id = dossier.org.id
    if kind == "revoked":
        await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    elif kind == "inactive":
        await dossier.db.execute(
            update(User).where(User.id == dossier.user.id).values(is_active=False)
        )
    elif kind == "deleted":
        await dossier.db.execute(delete(Document).where(Document.id == dossier.doc.id))
    elif kind == "common":
        await dossier.db.execute(
            update(Document).where(Document.id == dossier.doc.id).values(organisation_id=None)
        )
    await dossier.db.commit()
    with pytest.raises(HTTPException) as exc:
        await dossier.service.read(
            dossier.doc.id, org_id, dossier.user.id, manifest["extraction_id"], 24000
        )
    assert exc.value.status_code == 404
    assert dossier.storage.reads == []


@pytest.mark.parametrize("kind", ["revocation", "replacement"])
async def test_change_during_storage_io_prevents_response(dossier, monkeypatch, kind):
    manifest = await prepare(dossier)
    original_read = dossier.service._read_artifact

    async def change_during_read(record, budget):
        text = await original_read(record, budget)
        if kind == "revocation":
            await dossier.db.execute(
                delete(Membership).where(Membership.user_id == dossier.user.id)
            )
        else:
            await dossier.db.execute(
                update(Document).where(Document.id == dossier.doc.id).values(storage_path="new.txt")
            )
        await dossier.db.commit()
        return text

    monkeypatch.setattr(dossier.service, "_read_artifact", change_during_read)
    with pytest.raises(HTTPException) as exc:
        await read(dossier, manifest)
    assert exc.value.status_code == (404 if kind == "revocation" else 409)


async def test_budget_exceeded_never_returns_a_prefix(dossier):
    manifest = await prepare(dossier)
    with pytest.raises(HTTPException) as exc:
        await read(dossier, manifest, max_bytes=4)
    assert exc.value.status_code == 413
    assert dossier.storage.reads == []


@pytest.mark.parametrize("kind", ["missing", "tampered"])
async def test_broken_artifact_is_an_error_not_reextraction_or_excerpt(dossier, kind):
    manifest = await prepare(dossier)
    path = dossier.storage.puts[0]
    if kind == "missing":
        del dossier.storage.objects[path]
    else:
        dossier.storage.objects[path] = b"forged"
    with pytest.raises(HTTPException) as exc:
        await read(dossier, manifest)
    assert exc.value.status_code == 503
    assert len(dossier.storage.puts) == 1


@pytest.mark.parametrize("kind", ["empty", "extractor_failure", "storage_failure"])
async def test_failure_has_explicit_persisted_state(dossier, monkeypatch, kind):
    extractor = MagicMock()
    extractor.extract.return_value = " " if kind == "empty" else RAW
    if kind == "extractor_failure":
        extractor.extract.side_effect = ValueError("SENSITIVE PROVIDER DETAILS")
    if kind == "storage_failure":
        monkeypatch.setattr(
            dossier.storage, "put_file_bytes", MagicMock(side_effect=OSError("secret"))
        )
    with pytest.raises(ExtractionError):
        await dossier.service.extract(
            SourceSnapshot.from_document(dossier.doc), RAW.encode(), extractor
        )
    manifest = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    assert manifest["status"] == ("empty" if kind == "empty" else "error")
    assert manifest["error_code"]
    assert "secret" not in repr(manifest) and "SENSITIVE" not in repr(manifest)
    assert manifest["text_bytes"] is None


async def test_stale_source_snapshot_cannot_publish(dossier):
    snapshot = SourceSnapshot.from_document(dossier.doc)
    await dossier.db.execute(
        update(Document).where(Document.id == dossier.doc.id).values(storage_path="new.txt")
    )
    await dossier.db.commit()
    with pytest.raises(ExtractionError, match="source_version_changed"):
        await dossier.service.extract(snapshot, RAW.encode(), TextExtractor())
    assert dossier.storage.puts == []
    await dossier.db.rollback()


async def test_wrong_original_hash_cannot_publish(dossier):
    snapshot = SourceSnapshot.from_document(dossier.doc)
    with pytest.raises(ExtractionError, match="source_integrity_error"):
        await dossier.service.extract(snapshot, b"another version", TextExtractor())
    assert dossier.storage.puts == []


async def test_no_legacy_artifact_is_not_an_empty_document(dossier):
    result = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    assert result["status"] == "not_available"
    assert result["extraction_id"] is None
    assert dossier.storage.reads == []


async def test_full_ingestion_keeps_same_chunks_with_pilot_off_and_on(dossier, monkeypatch):
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.storage = dossier.storage
    pipeline.extractor = MagicMock(wraps=TextExtractor())
    pipeline.chunker = MagicMock()
    pipeline.chunker.chunk.side_effect = lambda text: [text]
    pipeline.qdrant = MagicMock()
    pipeline._cleanup_old_chunks = MagicMock()
    monkeypatch.setattr(
        "app.rag.ingestion._get_embeddings_with_progress", AsyncMock(return_value=[[0.1]])
    )
    monkeypatch.setattr(
        "app.rag.ingestion._get_sparse_vectors", lambda chunks: [{"indices": [1], "values": [1.0]}]
    )
    payloads = []
    for enabled in (False, True, True):
        monkeypatch.setattr(settings, "document_extraction_enabled", enabled)
        await pipeline.ingest(dossier.doc.id, dossier.db)
        assert dossier.doc.indexation_status == "indexed"
        payloads.append(pipeline.qdrant.upsert.call_args.kwargs["points"][0].payload)
    assert payloads[0] == payloads[1] == payloads[2]
    assert pipeline.extractor.extract.call_count == 2  # Last run reuses verified raw artifact.


async def test_common_corpus_stays_on_legacy_extractor(dossier, monkeypatch):
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    dossier.doc.organisation_id = None
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.extractor = TextExtractor()
    pipeline.storage = MagicMock()
    result = await pipeline._extract_document_text(dossier.doc, RAW.encode(), dossier.db)
    assert result == RAW
    assert not pipeline.storage.mock_calls


async def test_enabled_for_every_organisation_but_not_common_corpus(dossier, monkeypatch):
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    assert settings.document_extraction_enabled_for(dossier.org.id)
    assert settings.document_extraction_enabled_for(uuid.uuid4())
    assert not settings.document_extraction_enabled_for(None)
    monkeypatch.setattr(settings, "document_extraction_enabled", False)
    assert not settings.document_extraction_enabled_for(dossier.org.id)


async def test_http_flag_access_and_safe_json(dossier, client, monkeypatch):
    manifest = await prepare(dossier)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService", lambda: dossier.storage
    )
    url = (
        f"/api/v1/documents/{dossier.org.id}/{dossier.doc.id}"
        f"/extractions/{manifest['extraction_id']}/text"
    )
    monkeypatch.setattr(settings, "document_extraction_enabled", False)
    assert (await client.get(url)).status_code == 404
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    response = await client.get(url)
    assert response.status_code == 200
    assert response.json()["text"] == RAW
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "private, no-store"
    assert (await client.get(url, params={"max_bytes": 1})).status_code == 413
    assert (await client.get(url, params={"max_bytes": 2_000_000})).status_code == 422


async def test_deletion_removes_artifacts_even_when_pilot_disabled(dossier, monkeypatch):
    manifest = await prepare(dossier)
    monkeypatch.setattr(settings, "document_extraction_enabled", False)
    monkeypatch.setattr("app.services.document_service.storage", dossier.storage)
    monkeypatch.setattr(DocumentService, "_delete_qdrant_chunks", lambda *args: None)
    doc_id, org_id = dossier.doc.id, dossier.org.id
    await DocumentService(dossier.db).delete_document(doc_id, org_id)
    assert dossier.storage.objects == {}
    assert (await dossier.db.execute(select(DocumentExtraction))).scalars().all() == []
    with pytest.raises(HTTPException) as exc:
        await dossier.service.read(
            doc_id, org_id, dossier.user.id, manifest["extraction_id"], 24000
        )
    assert exc.value.status_code == 404


async def test_replacement_upload_failure_keeps_original(dossier, monkeypatch):
    storage = MagicMock()
    storage.upload_file = AsyncMock(side_effect=OSError("offline"))
    monkeypatch.setattr("app.services.document_service.storage", storage)
    original_path = dossier.doc.storage_path
    upload = UploadFile(
        BytesIO(b"new text"), filename="new.txt", headers=Headers({"content-type": "text/plain"})
    )
    with pytest.raises(OSError):
        await DocumentService(dossier.db).replace_document(
            dossier.doc.id, upload, dossier.user.id, dossier.org.id
        )
    storage.delete_file.assert_not_called()
    assert dossier.doc.storage_path == original_path


async def test_successful_replacement_rejects_previous_extraction(dossier, monkeypatch):
    manifest = await prepare(dossier)
    old_path = dossier.doc.storage_path
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    monkeypatch.setattr("app.services.document_service.storage", storage)
    upload = UploadFile(
        BytesIO(b"new text"), filename="new.txt", headers=Headers({"content-type": "text/plain"})
    )
    await DocumentService(dossier.db).replace_document(
        dossier.doc.id,
        upload,
        dossier.user.id,
        dossier.org.id,
    )
    assert dossier.doc.storage_path != old_path
    assert storage.mock_calls[0][0] == "upload_file"
    storage.delete_file.assert_called_once_with(old_path)
    with pytest.raises(HTTPException) as exc:
        await read(dossier, manifest)
    assert exc.value.status_code == 409
    assert dossier.storage.reads == []
    status = await dossier.service.status(dossier.doc.id, dossier.org.id, dossier.user.id)
    assert status["status"] == "not_available"


async def test_replacement_commit_failure_does_not_delete_original(dossier, monkeypatch):
    old_path = dossier.doc.storage_path
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    monkeypatch.setattr("app.services.document_service.storage", storage)
    monkeypatch.setattr(dossier.db, "commit", AsyncMock(side_effect=RuntimeError("db unavailable")))
    upload = UploadFile(
        BytesIO(b"new text"), filename="new.txt", headers=Headers({"content-type": "text/plain"})
    )
    with pytest.raises(RuntimeError, match="db unavailable"):
        await DocumentService(dossier.db).replace_document(
            dossier.doc.id,
            upload,
            dossier.user.id,
            dossier.org.id,
        )
    storage.delete_file.assert_not_called()
    await dossier.db.rollback()
    await dossier.db.refresh(dossier.doc)
    assert dossier.doc.storage_path == old_path


async def test_http_unknown_extraction_and_foreign_org_are_not_disclosed(
    dossier, client, monkeypatch
):
    manifest = await prepare(dossier)
    app.dependency_overrides[get_current_user] = lambda: dossier.user
    monkeypatch.setattr(
        "app.services.document_extraction_service.StorageService", lambda: dossier.storage
    )
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    root = "/api/v1/documents"
    foreign = await client.get(f"{root}/{dossier.other_org.id}/{dossier.doc.id}/extraction")
    assert foreign.status_code == 404
    unknown = await client.get(
        f"{root}/{dossier.org.id}/{dossier.doc.id}/extractions/{uuid.uuid4()}/text"
    )
    assert unknown.status_code == 404
    assert dossier.storage.reads == []
    current = await client.get(f"{root}/{dossier.org.id}/{dossier.doc.id}/extraction")
    assert current.status_code == 200
    assert current.json()["extraction_id"] == str(manifest["extraction_id"])


def test_docx_coverage_never_claims_headers_are_read():
    from app.services.document_extraction_service import coverage_manifest

    result = coverage_manifest("docx")
    assert "headers_footers_not_extracted" in result["limitations"]
    assert result["file_completeness"] == "not_certified"


async def test_org_erasure_also_deletes_extracted_objects(dossier, monkeypatch):
    from app.models.storage_operation import StorageOperation
    from app.services.organisation_service import OrganisationService

    await prepare(dossier)
    dossier.user.role = "admin"
    await dossier.db.commit()
    monkeypatch.setattr(settings, "document_extraction_enabled", False)
    monkeypatch.setattr("app.services.organisation_service.StorageService", lambda: dossier.storage)
    monkeypatch.setattr("app.services.organisation_service.get_qdrant_client", MagicMock())
    await OrganisationService(dossier.db).delete_organisation(dossier.org.id, dossier.user)
    assert dossier.storage.objects == {}
    assert (await dossier.db.execute(select(DocumentExtraction))).scalars().all() == []
    assert (await dossier.db.execute(select(StorageOperation))).scalars().all() == []


async def test_account_erasure_also_deletes_extracted_objects(dossier, monkeypatch):
    from app.models.account import Account
    from app.models.storage_operation import StorageOperation
    from app.services.data_retention_service import DataRetentionService

    await prepare(dossier)
    account = Account(id=uuid.uuid4(), name="Isolated test account", owner_id=dossier.user.id)
    dossier.db.add(account)
    dossier.org.account_id = account.id
    await dossier.db.commit()
    monkeypatch.setattr(settings, "document_extraction_enabled", False)
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: dossier.storage)
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", MagicMock())
    summary = await DataRetentionService(dossier.db).purge_account(account.id)
    assert dossier.storage.objects == {}
    assert summary["storage_objects_deleted"] == 2
    assert (await dossier.db.execute(select(DocumentExtraction))).scalars().all() == []
    assert (await dossier.db.execute(select(StorageOperation))).scalars().all() == []


async def test_erasure_failure_keeps_durable_intent_for_retry(dossier, monkeypatch):
    from app.models.storage_operation import StorageOperation
    from app.services.document_extraction_service import delete_extraction_artifacts
    from app.services.storage_operation_service import (
        StorageOperationService,
        finish_pending_storage_deletes,
    )

    await prepare(dossier)
    original_delete = dossier.storage.delete_file
    monkeypatch.setattr(dossier.storage, "delete_file", MagicMock(side_effect=OSError("offline")))
    await delete_extraction_artifacts(dossier.db, dossier.storage, [dossier.doc.id])
    dossier.storage.delete_file.assert_not_called()
    await dossier.db.commit()
    summary = await finish_pending_storage_deletes(dossier.db, dossier.storage)
    assert summary["failed"] == summary["pending"] == 1
    assert (await dossier.db.execute(select(DocumentExtraction))).scalars().all() == []
    operation = (await dossier.db.execute(select(StorageOperation))).scalar_one()
    assert operation.status == "delete_pending"
    assert operation.target_path in dossier.storage.objects
    monkeypatch.setattr(dossier.storage, "delete_file", original_delete)
    recovered = await StorageOperationService(dossier.db, dossier.storage).recover()
    assert recovered["deleted"] == 1
    assert operation.target_path not in dossier.storage.objects


async def test_delete_budget_reports_deferred_keys_not_only_first_batch(dossier):
    from app.services.storage_operation_service import (
        finish_pending_storage_deletes,
        queue_storage_delete,
    )

    for index in range(102):
        path = f"synthetic/retired-{index}"
        dossier.storage.objects[path] = b"retired"
        await queue_storage_delete(dossier.db, dossier.storage, dossier.doc.id, path)
    await dossier.db.commit()
    summary = await finish_pending_storage_deletes(dossier.db, dossier.storage)
    assert summary["deleted"] == 100
    assert summary["pending"] == 2
    assert dossier.doc.storage_path in dossier.storage.objects


async def test_storage_delete_rollback_does_not_erase_original(dossier):
    from app.services.storage_operation_service import (
        finish_pending_storage_deletes,
        queue_storage_delete,
    )

    await queue_storage_delete(
        dossier.db, dossier.storage, dossier.doc.id, dossier.doc.storage_path
    )
    await dossier.db.rollback()
    summary = await finish_pending_storage_deletes(dossier.db, dossier.storage)
    assert summary["deleted"] == 0
    assert len(dossier.storage.objects) == 1


async def test_queue_carries_expected_immutable_source(monkeypatch):
    from app.rag.tasks import enqueue_ingestion

    pool = SimpleNamespace(enqueue_job=AsyncMock())
    monkeypatch.setattr("app.rag.tasks.get_arq_pool", AsyncMock(return_value=pool))
    await enqueue_ingestion("document-id", expected_source="immutable/revision-key")
    pool.enqueue_job.assert_awaited_once_with(
        "run_ingestion", "document-id", expected_source="immutable/revision-key"
    )


async def test_quality_probe_compares_identical_production_prompts_without_api():
    from scripts.experiments.extraction_quality_probe import build_pairs

    pairs = await build_pairs()
    assert len(pairs) == 16
    for index in range(0, len(pairs), 2):
        a, b = pairs[index : index + 2]
        assert (a["variant"], b["variant"]) == ("A", "B")
        assert a["raw_text_sha256"] == b["raw_text_sha256"]
        assert a["messages"] == b["messages"]
        assert a["prompt_sha256"] == b["prompt_sha256"]


def test_additive_migration_round_trip_on_isolated_sqlite():
    import runpy
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = runpy.run_path(
        str(Path(__file__).parents[1] / "alembic/versions/e4f5docread01_document_extractions.py")
    )
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE documents (id CHAR(32) PRIMARY KEY, name TEXT)"))
            conn.execute(sa.text("INSERT INTO documents VALUES ('source', 'original kept')"))
            operations = Operations(MigrationContext.configure(conn))
            migration["upgrade"].__globals__["op"] = operations
            migration["upgrade"]()
            assert "document_extractions" in sa.inspect(conn).get_table_names()
            columns = {c["name"] for c in sa.inspect(conn).get_columns("document_extractions")}
            assert columns == set(DocumentExtraction.__table__.columns.keys())
            migration["downgrade"]()
            assert "document_extractions" not in sa.inspect(conn).get_table_names()
            assert (
                conn.execute(sa.text("SELECT name FROM documents")).scalar_one() == "original kept"
            )
    finally:
        engine.dispose()


def test_bounded_object_read_closes_stream_and_does_not_read_oversized_body():
    storage = StorageService.__new__(StorageService)
    storage.bucket = "test"
    storage.client = MagicMock()
    body = MagicMock()
    storage.client.get_object.return_value = {"Body": body, "ContentLength": 100}
    with pytest.raises(ValueError, match="read_budget_exceeded"):
        storage.get_file_bytes_bounded("exact/key", 10)
    body.read.assert_not_called()
    body.close.assert_called_once()
