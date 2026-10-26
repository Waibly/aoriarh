"""Source refresh must retain usable documents across technical failures."""

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.document import Document
from app.rag import ingestion
from app.services.boss_service import BossService, BossSyncResult
from app.services.kali_service import KaliService
from tests.conftest import test_session_factory as db_session_factory


@pytest.mark.parametrize("prefix,input_type", [
    ("common/code_travail/", None), ("common/dila/inca/", "document"),
])
async def test_embedding_batches_snapshot_metadata_before_progress_refresh(
    monkeypatch, prefix, input_type,
):
    async with db_session_factory() as db:
        doc = Document(
            name="Source", source_type="code_travail", storage_path=prefix + "source.txt",
        )
        db.add(doc)
        await db.commit()
        monkeypatch.setattr(ingestion, "EMBEDDING_BATCH_SIZE", 1)
        monkeypatch.setattr(ingestion, "EMBEDDING_CONCURRENCY", 1)
        embeddings = AsyncMock(return_value=[[0.1]])
        monkeypatch.setattr(ingestion, "_get_embeddings_batch", embeddings)

        async def progress(_value):
            # Reproduce the unloaded attribute window of db.refresh(doc),
            # without allowing an implicit database read between batches.
            db.expire(doc, ["storage_path"])

        result = await ingestion._get_embeddings_with_progress(
            ["Article A", "Article B", "Article C"], "test-key", doc, db,
            progress_callback=progress,
        )
        assert result == [[0.1], [0.1], [0.1]]
        assert embeddings.await_count == 3
        assert all(call.kwargs["input_type"] == input_type
                   for call in embeddings.await_args_list)


@pytest.mark.parametrize("status,vector_count,removed", [
    ("pending", 0, 0), ("error", 0, 0), ("indexed", 0, 0),
    ("indexed", 1, 0), ("indexed", 2, 1),
])
async def test_cleanup_requires_an_indexed_replacement_with_complete_vectors(
    monkeypatch, status, vector_count, removed,
):
    qdrant = Mock()
    qdrant.count.return_value = SimpleNamespace(count=vector_count)
    storage = Mock()
    monkeypatch.setattr("app.rag.qdrant_store.get_qdrant_client", lambda: qdrant)
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: storage)
    async with db_session_factory() as db:
        old_id = uuid.uuid4()
        db.add_all([
            Document(
                id=old_id, name="Code du travail", source_type="code_travail",
                storage_path="common/old.txt", indexation_status="indexed", chunk_count=2,
            ),
            Document(
                name="Code du travail", source_type="code_travail",
                storage_path="common/new.txt", indexation_status=status, chunk_count=2,
            ),
        ])
        await db.commit()
        assert await KaliService._cleanup_old_ccn_docs(db, [str(old_id)]) == removed
        assert (await db.get(Document, old_id) is None) == bool(removed)
        assert qdrant.delete.call_count == removed
        assert storage.delete_file.call_count == removed


async def test_boss_finds_the_admitted_source_after_its_storage_path_changes():
    service = BossService()
    path = "/portail/accueil/exonerations/exonerations-aide-a-domicile.html"
    source_url = "https://boss.gouv.fr" + path
    content = service._format_markdown("Source", "Exonérations", path, "Original source body")
    async with db_session_factory() as db:
        db.add(Document(
            name="Source", source_type="boss", source_url=source_url,
            storage_path="common/curated_maintenance/published/source.txt",
            file_hash=hashlib.sha256(content.encode()).hexdigest(),
            indexation_status="indexed",
        ))
        await db.commit()
        result = BossSyncResult()
        storage = Mock()
        await service._upsert_document(
            db, storage, uuid.uuid4(), path, "Exonérations", "<h1>Source</h1>",
            "Original source body", result,
        )
        assert result.docs_unchanged == 1
        assert result.docs_pending == result.docs_created == result.docs_updated == 0
        storage.put_file_bytes.assert_not_called()
