"""Une coupure réseau ponctuelle ne doit pas laisser un texte en erreur pour toujours.

Incident du 21/11/2026 : le décret 2026-1048 est resté en erreur après un
httpx.ConnectError vers Voyage, sans message, et la synchro JORF l'ignorait.
"""

import json
import logging
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.logging import setup_logging
from app.models.document import Document
from app.rag import ingestion
from app.services import jorf_service
from app.services.jorf_service import JorfService
from tests.conftest import test_session_factory as db_session_factory


def _ok_response():
    return httpx.Response(
        200,
        json={"data": [{"embedding": [0.1, 0.2]}], "usage": {"total_tokens": 0}},
        request=httpx.Request("POST", "https://api.voyageai.com/v1/embeddings"),
    )


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(ingestion.asyncio, "sleep", AsyncMock())


async def test_voyage_network_failure_is_retried():
    client = AsyncMock()
    client.post.side_effect = [httpx.ConnectError(""), _ok_response()]

    result = await ingestion._get_embeddings_batch(["texte"], "key", client)

    assert result == [[0.1, 0.2]]
    assert client.post.await_count == 2


async def test_voyage_server_error_is_retried():
    client = AsyncMock()
    request = httpx.Request("POST", "https://api.voyageai.com/v1/embeddings")
    client.post.side_effect = [httpx.Response(503, request=request), _ok_response()]

    assert await ingestion._get_embeddings_batch(["texte"], "key", client) == [[0.1, 0.2]]
    assert client.post.await_count == 2


async def test_voyage_network_failure_gives_up_after_max_retries():
    client = AsyncMock()
    client.post.side_effect = httpx.ConnectError("")

    with pytest.raises(httpx.ConnectError):
        await ingestion._get_embeddings_batch(["texte"], "key", client)
    assert client.post.await_count == ingestion.MAX_RETRIES


async def test_voyage_client_error_is_not_retried():
    client = AsyncMock()
    request = httpx.Request("POST", "https://api.voyageai.com/v1/embeddings")
    client.post.return_value = httpx.Response(400, text="bad", request=request)

    with pytest.raises(httpx.HTTPStatusError):
        await ingestion._get_embeddings_batch(["texte"], "key", client)
    assert client.post.await_count == 1


async def test_jorf_sync_requeues_texts_left_in_error(monkeypatch):
    enqueued = AsyncMock()
    monkeypatch.setattr(jorf_service, "enqueue_ingestion", enqueued)
    cid = f"JORFTEXT{uuid.uuid4().hex[:12]}"
    async with db_session_factory() as db:
        failed = Document(
            name="Décret en erreur",
            source_type="decret",
            storage_path=f"common/jorf/{cid}.txt",
            numero_pourvoi=cid,
            indexation_status="error",
        )
        indexed = Document(
            name="Décret indexé",
            source_type="decret",
            storage_path=f"common/jorf/{cid}-ok.txt",
            numero_pourvoi=cid + "OK",
            indexation_status="indexed",
        )
        db.add_all([failed, indexed])
        await db.commit()

        count = await JorfService()._requeue_failed(db)

    requeued = {call.args[0] for call in enqueued.await_args_list}
    assert str(failed.id) in requeued
    assert str(indexed.id) not in requeued
    assert count == len(requeued)


def test_json_logs_include_the_traceback(capsys):
    setup_logging(json_output=True)
    try:
        raise httpx.ConnectError("")
    except httpx.ConnectError:
        logging.getLogger("test").exception("Failed to index document %s", "x")

    lines = capsys.readouterr().out.splitlines()
    line = [entry for entry in lines if "Failed to index" in entry][-1]
    payload = json.loads(line)
    assert "Traceback" in payload["exception"]
    assert "ConnectError" in payload["exception"]
