"""Opt-in integration tests. Dedicated loopback PostgreSQL/MinIO/Qdrant only.

No paid embedding, no application database, no existing bucket or collection.
Set AORIA_TEST_POSTGRES_URL, AORIA_TEST_MINIO_URL, AORIA_TEST_QDRANT_URL.
"""

import asyncio
import hashlib
import os
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlparse

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, SparseVectorParams, VectorParams
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.core.config import settings
from app.models.base import Base
from app.models.document import Document
from app.models.organisation import Organisation
from app.models.storage_operation import StorageOperation
from app.models.user import User
from app.rag.chunker import LegalChunker
from app.rag.ingestion import IngestionPipeline
from app.rag.text_extractor import TextExtractor
from app.services.document_extraction_service import DocumentExtractionService, SourceSnapshot
from app.services.document_service import DocumentService
from app.services.storage_operation_service import StorageOperationService, finish_storage_io
from app.services.storage_service import StorageService


def upload(value):
    return UploadFile(
        filename="replacement.txt",
        file=BytesIO(value),
        headers=Headers({"content-type": "text/plain"}),
    )


@pytest.fixture
async def isolated(monkeypatch):
    urls = [
        os.getenv(key)
        for key in ("AORIA_TEST_POSTGRES_URL", "AORIA_TEST_MINIO_URL", "AORIA_TEST_QDRANT_URL")
    ]
    if not all(urls):
        pytest.skip("explicit isolated service URLs required")
    assert all(urlparse(url).hostname in {"127.0.0.1", "localhost"} for url in urls)
    assert urlparse(urls[0]).path == "/aoria_lot1b", "dedicated test database required"
    identifier = "aoria_probe_" + uuid.uuid4().hex
    engine = create_async_engine(
        urls[0], execution_options={"schema_translate_map": {None: identifier}}
    )
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{identifier}"'))
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = StorageService.__new__(StorageService)
    storage.bucket = identifier.replace("_", "-")
    storage._bucket_ready = False
    storage.client = boto3.client(
        "s3",
        endpoint_url=urls[1],
        aws_access_key_id="isolated_test",
        aws_secret_access_key="isolated_test_only",
        region_name="us-east-1",
    )
    storage._ensure_bucket()
    qdrant = QdrantClient(url=urls[2], timeout=10)
    qdrant.create_collection(
        identifier,
        vectors_config={"dense": VectorParams(size=4, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse-bm25": SparseVectorParams()},
    )
    monkeypatch.setattr("app.rag.ingestion.COLLECTION_NAME", identifier)
    monkeypatch.setattr("app.services.document_service.storage", storage)
    monkeypatch.setattr(settings, "document_extraction_enabled", True)
    async with factory() as db:
        org = Organisation(id=uuid.uuid4(), name="Synthetic isolated org")
        user = User(id=uuid.uuid4(), email=f"{identifier}@example.test", full_name="Test")
        db.add_all([org, user])
        await db.flush()
        source = b"Version A. Date limite : 4 avril."
        doc = Document(
            id=uuid.uuid4(),
            organisation_id=org.id,
            uploaded_by=user.id,
            name="source.txt",
            source_type="divers",
            file_format="txt",
            storage_path=f"{org.id}/original.txt",
            file_hash=hashlib.sha256(source).hexdigest(),
        )
        db.add(doc)
        await db.commit()
        storage.put_file_bytes(doc.storage_path, source)
        monkeypatch.setattr(settings, "document_extraction_organisation_ids", [org.id])
        seed = dict(doc_id=doc.id, org_id=org.id, user_id=user.id, old_path=doc.storage_path)

    async def embeddings(chunks, *args, **kwargs):
        return [[1.0, 0.0, 0.0, 0.0] for _ in chunks]

    monkeypatch.setattr("app.rag.ingestion._get_embeddings_with_progress", embeddings)
    monkeypatch.setattr(
        "app.rag.ingestion._get_sparse_vectors",
        lambda chunks: [dict(indices=[1], values=[1.0]) for _ in chunks],
    )

    def pipeline():
        value = IngestionPipeline.__new__(IngestionPipeline)
        value.storage, value.qdrant = storage, qdrant
        value.extractor, value.chunker = TextExtractor(), LegalChunker()
        return value

    try:
        yield SimpleNamespace(
            factory=factory,
            storage=storage,
            qdrant=qdrant,
            collection=identifier,
            pipeline=pipeline,
            **seed,
        )
    finally:
        qdrant.delete_collection(identifier)
        qdrant.close()
        # Only keys within the bucket created by this fixture.
        listing = storage.client.list_objects_v2(Bucket=storage.bucket)
        for item in listing.get("Contents", []):
            storage.client.delete_object(Bucket=storage.bucket, Key=item["Key"])
        storage.client.delete_bucket(Bucket=storage.bucket)
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{identifier}" CASCADE'))
        await engine.dispose()


async def test_old_worker_cannot_publish_after_replacement(isolated, monkeypatch):
    env = isolated
    async with env.factory() as db:
        await env.pipeline().ingest(env.doc_id, db, expected_source=env.old_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_embeddings(chunks, *args, **kwargs):
        if "Version A" in chunks[0]:
            entered.set()
            await release.wait()
        return [[1.0, 0.0, 0.0, 0.0] for _ in chunks]

    monkeypatch.setattr("app.rag.ingestion._get_embeddings_with_progress", paused_embeddings)

    async def old_worker():
        async with env.factory() as db:
            await env.pipeline().ingest(env.doc_id, db, expected_source=env.old_path)

    task = asyncio.create_task(old_worker())
    try:
        await asyncio.wait_for(entered.wait(), 10)
        async with env.factory() as db:
            doc = await DocumentService(db).replace_document(
                env.doc_id, upload(b"Version B. Date limite : 18 avril."), env.user_id, env.org_id
            )
            new_path = doc.storage_path
            await env.pipeline().ingest(env.doc_id, db, expected_source=new_path)
        release.set()
        await asyncio.wait_for(task, 10)
        async with env.factory() as db:
            current = await db.get(Document, env.doc_id)
            assert current.storage_path == new_path
            assert current.indexation_status == "indexed"
            assert current.indexation_error is None
        points, _ = env.qdrant.scroll(env.collection, with_payload=True)
        assert points and all("Version B" in p.payload["text"] for p in points)
    finally:
        release.set()
        await task


async def test_queued_obsolete_source_does_no_storage_work(isolated, monkeypatch):
    env = isolated
    pipeline = env.pipeline()
    pipeline.storage = MagicMock()
    async with env.factory() as db:
        await pipeline.ingest(env.doc_id, db, expected_source="obsolete-key")
        doc = await db.get(Document, env.doc_id)
        assert doc.indexation_status == "pending"
    pipeline.storage.get_file_bytes.assert_not_called()


async def test_delete_refreshes_cached_parent_after_replacement(isolated, monkeypatch):
    env = isolated
    monkeypatch.setattr(DocumentService, "_delete_qdrant_chunks", lambda *args: None)
    async with env.factory() as deleting, env.factory() as replacing:
        cached = await DocumentService(deleting).get_document(env.doc_id, env.org_id)
        current = await DocumentService(replacing).replace_document(
            env.doc_id, upload(b"Newest source to erase"), env.user_id, env.org_id
        )
        new_path = current.storage_path
        assert cached.storage_path == env.old_path
        await DocumentService(deleting).delete_document(env.doc_id, env.org_id)
        assert cached.storage_path == new_path
        assert (await deleting.execute(select(StorageOperation))).scalars().all() == []
        assert "Contents" not in env.storage.client.list_objects_v2(Bucket=env.storage.bucket)


async def test_qdrant_cleanup_failure_is_not_reported_as_indexed(isolated, monkeypatch):
    env = isolated
    pipeline = env.pipeline()
    monkeypatch.setattr(
        pipeline, "_cleanup_old_chunks", MagicMock(side_effect=OSError("cleanup unavailable"))
    )
    async with env.factory() as db:
        await pipeline.ingest(env.doc_id, db, expected_source=env.old_path)
        current = await db.get(Document, env.doc_id)
        assert current.indexation_status == "error"
    # Known boundary: SQL error state is honest, but the Qdrant write already
    # happened. Active-revision filtering remains necessary before activation.
    points, _ = env.qdrant.scroll(env.collection)
    assert points


async def test_concurrent_replacement_rejects_stale_writer_before_put(isolated, monkeypatch):
    env = isolated
    entered, release = asyncio.Event(), asyncio.Event()
    actual_upload = env.storage.upload_file
    uploads = []

    async def gated_upload(file, path):
        uploads.append(path)
        entered.set()
        await release.wait()
        return await actual_upload(file, path)

    monkeypatch.setattr(env.storage, "upload_file", gated_upload)
    async with env.factory() as first, env.factory() as second:
        # Both sessions genuinely observed the same revision.
        cached = await DocumentService(second).get_document(env.doc_id, env.org_id)

        async def replace(db, value):
            return await DocumentService(db).replace_document(
                env.doc_id, upload(value), env.user_id, env.org_id
            )

        one = asyncio.create_task(replace(first, b"First replacement"))
        await asyncio.wait_for(entered.wait(), 10)
        two = asyncio.create_task(replace(second, b"Second replacement"))
        # Synchronize via observed reservation, not an assumed timing delay.
        for _ in range(100):
            async with env.factory() as observer:
                rows = (await observer.execute(select(StorageOperation))).scalars().all()
            if len(rows) >= 2:
                break
            await asyncio.sleep(0.01)
        assert len(rows) >= 2
        release.set()
        await asyncio.wait_for(one, 10)
        with pytest.raises(HTTPException) as exc:
            await asyncio.wait_for(two, 10)
        assert exc.value.status_code == 409
        assert len(uploads) == 1
        assert cached is not None


async def test_successful_put_failed_commit_is_recoverable(isolated, monkeypatch):
    env = isolated
    async with env.factory() as db:
        doc = await db.get(Document, env.doc_id)
        original_commit = db.commit

        async def fail_publication():
            # Reservation commit succeeds; the ready publication fails.
            if any(
                isinstance(obj, StorageOperation) and obj.status == "retained" for obj in db.dirty
            ):
                raise OSError("injected commit failure")
            await original_commit()

        monkeypatch.setattr(db, "commit", fail_publication)
        with pytest.raises(OSError, match="injected"):
            await DocumentExtractionService(db, env.storage).extract(
                SourceSnapshot.from_document(doc),
                env.storage.get_file_bytes(env.old_path),
                TextExtractor(),
            )
        await db.rollback()
    async with env.factory() as db:
        operation = (await db.execute(select(StorageOperation))).scalar_one()
        assert operation.status == "writing"
        assert env.storage.get_file_bytes(operation.target_path)
        summary = await StorageOperationService(db, env.storage).recover(grace_seconds=0)
        assert summary["deleted"] == 1
        assert env.storage.get_file_bytes(env.old_path).startswith(b"Version A")
        with pytest.raises(ClientError):
            env.storage.get_file_bytes(operation.target_path)


async def test_recovery_skips_locked_writer_and_preserves_referenced_source(isolated):
    env = isolated
    async with env.factory() as writer, env.factory() as recovery:
        service = StorageOperationService(writer, env.storage)
        identifier = await service.reserve(env.doc_id, "in-flight-key", "original")
        await service.lock_write(identifier)
        summary = await StorageOperationService(recovery, env.storage).recover(grace_seconds=0)
        assert summary["skipped"] == 1
        await writer.rollback()
        await service.schedule_delete(env.doc_id, env.old_path)
        await writer.commit()
        summary = await StorageOperationService(recovery, env.storage).recover(grace_seconds=0)
        assert summary["retained"] == 1
        assert env.storage.get_file_bytes(env.old_path)


async def test_delete_failure_persists_after_parent_deletion_and_retries_are_bounded(
    isolated, monkeypatch
):
    env = isolated
    monkeypatch.setattr(DocumentService, "_delete_qdrant_chunks", lambda *args: None)
    original_delete = env.storage.delete_file
    monkeypatch.setattr(env.storage, "delete_file", MagicMock(side_effect=OSError("offline")))
    async with env.factory() as db:
        await DocumentService(db).delete_document(env.doc_id, env.org_id)
    async with env.factory() as db:
        assert await db.get(Document, env.doc_id) is None
        service = StorageOperationService(db, env.storage)
        for _ in range(7):
            await service.recover()
        operation = (await db.execute(select(StorageOperation))).scalar_one()
        assert operation.status == "delete_pending" and operation.attempts == 5
        assert env.storage.delete_file.call_count == 5
        # Explicit operator reset, not an unbounded automatic retry.
        operation.attempts = 0
        await db.commit()
        monkeypatch.setattr(env.storage, "delete_file", original_delete)
        summary = await service.recover()
        assert summary["deleted"] == 1


async def test_cancelled_storage_io_finishes_before_lock_scope_can_exit():
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def put():
        entered.set()
        await release.wait()
        completed.set()

    task = asyncio.create_task(finish_storage_io(put()))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed.is_set()


async def test_both_additive_migrations_round_trip_postgres(isolated):
    import runpy
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    schema = "aoria_migration_" + uuid.uuid4().hex
    engine = create_async_engine(os.environ["AORIA_TEST_POSTGRES_URL"])

    def migrate(conn):
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text("CREATE TABLE documents (id UUID PRIMARY KEY, name TEXT)"))
        identifier = uuid.uuid4()
        conn.execute(
            text("INSERT INTO documents VALUES (:id, 'preserved original')"), {"id": identifier}
        )
        operations = Operations(MigrationContext.configure(conn))
        migrations = []
        for name in ("e4f5docread01_document_extractions.py", "f5g6docops01_storage_operations.py"):
            migration = runpy.run_path(str(Path(__file__).parents[1] / "alembic/versions" / name))
            migration["upgrade"].__globals__["op"] = operations
            migration["upgrade"]()
            migrations.append(migration)
        assert set(sa.inspect(conn).get_table_names(schema=schema)) == {
            "documents",
            "document_extractions",
            "storage_operations",
        }
        assert {
            c["name"] for c in sa.inspect(conn).get_columns("storage_operations", schema=schema)
        } == set(StorageOperation.__table__.columns.keys())
        for migration in reversed(migrations):
            migration["downgrade"]()
        assert (
            conn.execute(
                text("SELECT name FROM documents WHERE id=:id"), {"id": identifier}
            ).scalar_one()
            == "preserved original"
        )
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

    try:
        async with engine.begin() as conn:
            await conn.run_sync(migrate)
    finally:
        await engine.dispose()
