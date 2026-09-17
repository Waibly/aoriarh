"""Library-to-chat technical contracts. No paid API or editorial evaluator."""
# ruff: noqa: F401, F811 -- shared pytest fixtures

import hashlib
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, func, select

from app.models.document import Document
from app.models.document_extraction import DocumentExtraction
from app.models.membership import Membership
from app.rag.text_extractor import TextExtractor
from tests.test_chat_document_journey import journey
from tests.test_conversation_documents import planner, task_payload
from tests.test_document_extraction_service import dossier


async def test_search_is_tenant_scoped_includes_divers_and_filters_literal_name_dates(
    journey, dossier, client
):
    dossier.doc.name = "Compte rendu mars_100%.txt"
    dossier.doc.created_at = datetime(2026, 3, 31, 23, 59, tzinfo=UTC)
    dossier.db.add(
        Document(
            id=uuid.uuid4(),
            organisation_id=dossier.other_org.id,
            name=dossier.doc.name,
            source_type="divers",
            storage_path="foreign",
        )
    )
    await dossier.db.commit()
    url = f"{journey.url}/document-library"
    response = await client.get(
        url,
        params={"name": "MARS_100%", "uploaded_from": "2026-03-01", "uploaded_to": "2026-03-31"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert [d["document_id"] for d in response.json()["items"]] == [str(dossier.doc.id)]
    assert "storage_path" not in response.text
    response = await client.get(url, params={"uploaded_from": "2026-04-01"})
    assert response.json()["items"] == []
    response = await client.get(url, params={"name": "not found"})
    assert response.json()["items"] == []


async def test_pagination_keeps_ambiguous_names_as_separate_choices(journey, dossier, client):
    for _ in range(3):
        dossier.db.add(
            Document(
                id=uuid.uuid4(),
                organisation_id=dossier.org.id,
                name="Entretien.txt",
                source_type="divers",
                storage_path=str(uuid.uuid4()),
            )
        )
    await dossier.db.commit()
    first = (
        await client.get(
            f"{journey.url}/document-library", params={"name": "Entretien", "limit": 2}
        )
    ).json()
    second = (
        await client.get(
            f"{journey.url}/document-library", params={"name": "Entretien", "limit": 2, "offset": 2}
        )
    ).json()
    assert first["has_more"] is True and second["has_more"] is False
    ids = [d["document_id"] for d in first["items"] + second["items"]]
    assert len(ids) == len(set(ids)) == 3


@pytest.mark.parametrize(
    "params",
    [
        {"offset": -1},
        {"limit": 51},
        {"name": "x" * 201},
        {"uploaded_from": "2026-04-02", "uploaded_to": "2026-04-01"},
        {"uploaded_to": "9999-12-31"},
        {"uploaded_from": "invalid"},
    ],
)
async def test_search_rejects_invalid_parameters(journey, client, params):
    assert (await client.get(f"{journey.url}/document-library", params=params)).status_code == 422


async def test_legacy_file_prepared_once_without_duplicate_or_reindex(
    journey, dossier, client, monkeypatch
):
    count = await dossier.db.scalar(select(func.count()).select_from(Document))
    extract = MagicMock(wraps=TextExtractor().extract)
    monkeypatch.setattr(TextExtractor, "extract", extract)
    enqueue = AsyncMock()
    monkeypatch.setattr("app.rag.tasks.enqueue_ingestion", enqueue)
    url = f"{journey.url}/document-library/{dossier.doc.id}"
    first = await client.post(url, json={"source_sha256": dossier.doc.file_hash})
    assert first.status_code == 200, first.text
    second = await client.post(url, json={"source_sha256": dossier.doc.file_hash})
    assert second.status_code == 200, second.text
    assert first.json()["extraction_id"] == second.json()["extraction_id"]
    assert await dossier.db.scalar(select(func.count()).select_from(Document)) == count
    assert await dossier.db.scalar(select(func.count()).select_from(DocumentExtraction)) == 1
    assert extract.call_count == 1
    enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "fault,expected",
    [
        ("foreign", 404),
        ("revoked", 404),
        ("stale", 409),
        ("missing", 404),
    ],
)
async def test_selection_rechecks_access_and_version(journey, dossier, client, fault, expected):
    document_id = dossier.doc.id
    old_hash = dossier.doc.file_hash
    if fault == "foreign":
        dossier.doc.organisation_id = dossier.other_org.id
    elif fault == "revoked":
        await dossier.db.execute(delete(Membership).where(Membership.user_id == dossier.user.id))
    elif fault == "stale":
        dossier.doc.file_hash = "b" * 64
    else:
        document_id = uuid.uuid4()
    await dossier.db.commit()
    response = await client.post(
        f"{journey.url}/document-library/{document_id}", json={"source_sha256": old_hash}
    )
    assert response.status_code == expected, response.text
    assert not dossier.storage.reads
    if fault == "revoked":
        assert (await client.get(f"{journey.url}/document-library")).status_code == 404


@pytest.mark.parametrize("failure,expected", [("missing_file", 503), ("too_long", 413)])
async def test_no_attachment_confirmed_on_unreadable_or_oversized_text(
    journey, dossier, client, failure, expected
):
    if failure == "missing_file":
        del dossier.storage.objects[dossier.doc.storage_path]
    else:
        raw = b"x" * 24_001
        dossier.storage.objects[dossier.doc.storage_path] = raw
        dossier.doc.file_hash = hashlib.sha256(raw).hexdigest()
        await dossier.db.commit()
    response = await client.post(
        f"{journey.url}/document-library/{dossier.doc.id}",
        json={"source_sha256": dossier.doc.file_hash},
    )
    assert response.status_code == expected, response.text


async def test_corrupt_existing_extraction_is_not_rebuilt(journey, dossier, client):
    url = f"{journey.url}/document-library/{dossier.doc.id}"
    first = await client.post(url, json={"source_sha256": dossier.doc.file_hash})
    assert first.status_code == 200
    artifact = dossier.storage.puts[-1]
    dossier.storage.objects[artifact] = b"corrupt"
    puts = len(dossier.storage.puts)
    response = await client.post(url, json={"source_sha256": dossier.doc.file_hash})
    assert response.status_code == 503
    assert len(dossier.storage.puts) == puts


async def test_library_selection_reaches_chat_and_is_inherited(
    journey, dossier, client, monkeypatch
):
    response = await client.post(
        f"{journey.url}/document-library/{dossier.doc.id}",
        json={"source_sha256": dossier.doc.file_hash},
    )
    assert response.status_code == 200
    reference = {key: response.json()[key] for key in ("document_id", "extraction_id")}
    agent = planner(json.dumps(task_payload("documents")))
    texts = []

    async def generate(query, results, **kwargs):
        texts.append(results[0].text)
        yield "  Sortie brute conservée\n"

    agent.stream_generate = generate
    monkeypatch.setattr("app.api.conversations.RAGAgent", lambda: agent)
    first = await client.post(
        journey.url + "/chat/stream",
        json={
            "message": "Lis ce document existant",
            "document_references": [reference],
        },
    )
    assert "chat_done" in first.text, first.text
    second = await client.post(journey.url + "/chat/stream", json={"message": "Et ses dates ?"})
    assert "chat_done" in second.text, second.text
    assert texts == [dossier.storage.objects[dossier.doc.storage_path].decode()] * 2
    history = (await client.get(journey.url)).json()["messages"]
    answers = [m["content"] for m in history if m["role"] == "assistant"]
    assert answers == ["  Sortie brute conservée\n"] * 2


async def test_other_users_conversation_cannot_be_searched(journey, dossier, client):
    journey.conv.user_id = uuid.uuid4()
    await dossier.db.commit()
    assert (await client.get(f"{journey.url}/document-library")).status_code == 403
