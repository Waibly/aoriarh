from unittest.mock import AsyncMock, MagicMock
import uuid
from app import worker


async def test_paused_collector_never_opens_database(monkeypatch):
    monkeypatch.setattr(worker.settings, "judilibre_ca_collection_enabled", False)
    assert await worker.run_judilibre_ca_collection({}) == {"status": "paused"}


async def test_paused_registered_ingestion_never_calls_paid_pipeline(monkeypatch):
    monkeypatch.setattr(worker.settings, "judilibre_ca_collection_enabled", False)
    db = AsyncMock()
    db.scalar.return_value = "source-id"
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = db
    pipeline = MagicMock()
    monkeypatch.setattr(worker, "IngestionPipeline", pipeline)
    await worker.run_ingestion({"session_factory": factory}, str(uuid.uuid4()))
    pipeline.assert_not_called()


async def test_other_ingestion_continues_during_pause(monkeypatch):
    monkeypatch.setattr(worker.settings, "judilibre_ca_collection_enabled", False)
    db = AsyncMock()
    db.scalar.return_value = None
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = db
    pipeline = MagicMock()
    pipeline.return_value.ingest = AsyncMock()
    monkeypatch.setattr(worker, "IngestionPipeline", pipeline)
    await worker.run_ingestion({"session_factory": factory}, str(uuid.uuid4()))
    pipeline.return_value.ingest.assert_awaited_once()
