import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from app.services.curated_source_service import CuratedSourceService, extract_body, fetch_source


SPEC = {
    "key": "test",
    "format": "html",
    "xpath": "//article",
    "url": "https://example.org/guide",
    "allowed_hosts": ["example.org"],
    "document_id": str(uuid.uuid4()),
    "source_type": "documentation_officielle",
    "policy": "refresh",
    "name": "Guide",
    "baseline_document_sha256": "old",
}
RAW = b'<html><nav>Menu</nav><article><h1>Source</h1><p>Original source text <a href="/law">law</a></p></article></html>'


def test_source_structure_and_links():
    body = extract_body(SPEC, RAW)
    assert "Original source text" in body
    assert "https://example.org/law" in body
    assert "Menu" not in body


@pytest.mark.parametrize(
    "raw",
    [
        b"<html>Request rejected</html>",
        b"<article></article>",
        b"<article>A</article><article>B</article>",
    ],
)
def test_invalid_source_never_replaces_document(raw):
    with pytest.raises(ValueError):
        extract_body(SPEC, raw)


@pytest.mark.asyncio
async def test_cross_host_redirect_is_not_followed():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Unapproved"):
            await fetch_source(client, SPEC)
    assert requested == [SPEC["url"]]


@pytest.mark.asyncio
async def test_empty_download_is_failure():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as client:
        with pytest.raises(ValueError, match="Empty"):
            await fetch_source(client, SPEC)


def setup_service():
    storage = Mock()
    service = CuratedSourceService(storage)
    service.read_json = Mock(return_value=None)
    service.save_json = Mock()
    service.replace = AsyncMock()
    doc = SimpleNamespace(
        id=uuid.UUID(SPEC["document_id"]),
        organisation_id=None,
        private_dossier_id=None,
        private_conversation_id=None,
        retired_at=None,
        source_type=SPEC["source_type"],
        source_url=SPEC["url"],
        file_hash="old",
        indexation_status="indexed",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=doc), rollback=AsyncMock())
    return service, db, doc


@pytest.mark.asyncio
async def test_unchanged_source_does_not_embed():
    service, db, doc = setup_service()
    spec = dict(
        SPEC, baseline_body_sha256=hashlib.sha256(extract_body(SPEC, RAW).encode()).hexdigest()
    )
    with patch(
        "app.services.curated_source_service.fetch_source",
        new=AsyncMock(return_value=(RAW, SPEC["url"])),
    ):
        result = await service.sync(db, sources=[spec])
    assert result["unchanged"] == 1
    assert result["tokens_reserved"] == 0
    service.replace.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("organisation_id", uuid.uuid4()),
        ("private_dossier_id", uuid.uuid4()),
        ("retired_at", "retired"),
        ("source_url", "https://example.org/other"),
    ],
)
async def test_private_retired_or_wrong_document_never_modified(field, value):
    service, db, doc = setup_service()
    setattr(doc, field, value)
    with patch(
        "app.services.curated_source_service.fetch_source",
        new=AsyncMock(return_value=(RAW, SPEC["url"])),
    ):
        result = await service.sync(db, sources=[SPEC])
    assert result["errors"] == 1
    service.replace.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_admitted_source_only_archived():
    service, db, doc = setup_service()
    with patch(
        "app.services.curated_source_service.fetch_source",
        new=AsyncMock(return_value=(RAW, SPEC["url"])),
    ):
        result = await service.sync(db, sources=[dict(SPEC, policy="review")])
    assert result["pending"] == 1
    assert result["updated"] == 0
    service.replace.assert_not_awaited()


@pytest.mark.asyncio
async def test_error_keeps_old_document_and_continues_next_source():
    service, db, doc = setup_service()
    spec = dict(
        SPEC, baseline_body_sha256=hashlib.sha256(extract_body(SPEC, RAW).encode()).hexdigest()
    )
    with patch(
        "app.services.curated_source_service.fetch_source",
        new=AsyncMock(side_effect=[ValueError("blocked"), (RAW, SPEC["url"])]),
    ):
        result = await service.sync(db, sources=[dict(spec, key="blocked"), spec])
    assert result["errors"] == result["unchanged"] == 1
    assert doc.file_hash == "old"
    service.replace.assert_not_awaited()


def test_registry_is_bounded_and_identifiers_unique():
    from app.services.curated_source_registry import SOURCES

    assert len({s["key"] for s in SOURCES}) == len(SOURCES)
    assert len({s["document_id"] for s in SOURCES if s.get("document_id")}) == sum(
        bool(s.get("document_id")) for s in SOURCES
    )
    for spec in SOURCES:
        if spec["policy"] == "refresh":
            assert spec["source_type"] in {"documentation_officielle", "code_procedure_civile"}


@pytest.mark.asyncio
async def test_changed_guide_is_refreshed_with_reserved_budget():
    service, db, doc = setup_service()
    fake_pipeline = Mock()
    fake_pipeline.chunker.chunk.return_value = ["source body"]
    with (
        patch(
            "app.services.curated_source_service.fetch_source",
            new=AsyncMock(return_value=(RAW, SPEC["url"])),
        ),
        patch("app.rag.ingestion.IngestionPipeline", return_value=fake_pipeline),
    ):
        result = await service.sync(db, sources=[SPEC])
    assert result["updated"] == 1
    assert result["tokens_reserved"] > 0
    service.replace.assert_awaited_once()


@pytest.mark.asyncio
async def test_budget_exhaustion_keeps_original_without_embedding():
    service, db, doc = setup_service()
    fake_pipeline = Mock()
    fake_pipeline.chunker.chunk.return_value = ["source body"]
    with (
        patch(
            "app.services.curated_source_service.fetch_source",
            new=AsyncMock(return_value=(RAW, SPEC["url"])),
        ),
        patch("app.rag.ingestion.IngestionPipeline", return_value=fake_pipeline),
        patch("app.services.curated_source_service.MAX_RUN_TOKENS", 0),
    ):
        result = await service.sync(db, sources=[SPEC])
    assert result["pending"] == 1
    assert result["sources"][0]["status"] == "budget_pending"
    assert result["tokens_reserved"] == 0
    service.replace.assert_not_awaited()


@pytest.mark.asyncio
async def test_identical_raw_source_avoids_reindex_on_pdf_parser_version_change():
    service, db, doc = setup_service()
    spec = dict(
        SPEC,
        baseline_body_sha256="different-parser-rendering",
        baseline_raw_sha256=hashlib.sha256(RAW).hexdigest(),
    )
    with patch(
        "app.services.curated_source_service.fetch_source",
        new=AsyncMock(return_value=(RAW, SPEC["url"])),
    ):
        result = await service.sync(db, sources=[spec])
    assert result["unchanged"] == 1
    service.replace.assert_not_awaited()


@pytest.mark.asyncio
async def test_cpc_requires_all_selected_current_articles_and_preserves_notes():
    from datetime import date
    from app.services.curated_source_service import fetch_cpc

    data = {
        "sections": [
            {
                "title": "Juridiction spécifique",
                "articles": [
                    {
                        "num": "9",
                        "etat": "VIGUEUR",
                        "id": "LEGIARTI1",
                        "content": "<p>Original</p>",
                        "nota": "<p>Application différée</p>",
                    },
                ],
            }
        ]
    }
    with patch("app.services.legi_service.LegiService._api_post", new=AsyncMock(return_value=data)):
        body, raw = await fetch_cpc({"articles": ["9"]}, date(2026, 10, 8))
        assert "Juridiction spécifique" in body
        assert "Application différée" in body
        assert json.loads(raw) == data
        with pytest.raises(ValueError, match="missing"):
            await fetch_cpc({"articles": ["9", "11"]}, date(2026, 10, 8))


@pytest.mark.asyncio
async def test_index_failure_restores_document_and_vectors():
    from app.models.document import Document
    from qdrant_client.models import Record

    service = CuratedSourceService(Mock())
    service.save_json = Mock()
    doc = Document(
        id=uuid.uuid4(),
        name="Old",
        source_type="documentation_officielle",
        source_url=SPEC["url"],
        file_hash="old",
        storage_path="original",
        file_format="txt",
        indexation_status="indexed",
        chunk_count=1,
    )
    old_point = Record(
        id=str(uuid.uuid4()),
        vector={"dense": [0.5]},
        payload={"organisation_id": "common", "private": False},
    )
    pipeline = Mock()
    pipeline.qdrant.scroll.return_value = ([old_point], None)
    pipeline.ingest = AsyncMock(side_effect=RuntimeError("embedding transport failed"))
    db = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    service.storage.get_file_bytes_bounded.return_value = b"new"
    with pytest.raises(RuntimeError, match="transport"):
        await service.replace(db, doc, "new", pipeline, 10, name="New")
    assert doc.file_hash == "old" and doc.storage_path == "original" and doc.name == "Old"
    assert doc.indexation_status == "indexed"
    pipeline.qdrant.upsert.assert_called_once()
    pipeline._cleanup_old_chunks.assert_called_once_with(
        str(doc.id), {str(old_point.id)}, strict=True
    )


@pytest.mark.asyncio
async def test_status_requires_admin(client, manager_user):
    response = await client.get(
        "/api/v1/admin/syncs/curated-sources/status",
        headers={"Authorization": "Bearer " + manager_user["token"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_status_reports_blocked_sources_without_triggering_import(client, admin_user):
    report = {"errors": 1, "sources": [{"key": "ameli", "status": "error", "error": "403"}]}
    with (
        patch(
            "app.services.curated_source_service.CuratedSourceService.read_json",
            return_value=report,
        ),
        patch(
            "app.services.curated_source_service.CuratedSourceService.sync", new_callable=AsyncMock
        ) as sync,
    ):
        response = await client.get(
            "/api/v1/admin/syncs/curated-sources/status",
            headers={"Authorization": "Bearer " + admin_user["token"]},
        )
    assert response.status_code == 200
    assert response.json() == report
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_forbidden_source_is_explicit_and_preserves_document():
    service, db, doc = setup_service()
    response = httpx.Response(403, request=httpx.Request("GET", SPEC["url"]))
    with patch("app.services.curated_source_service.fetch_source", new=AsyncMock(
        side_effect=httpx.HTTPStatusError("Forbidden", request=response.request, response=response)
    )):
        result = await service.sync(db, sources=[SPEC])
    assert result["errors"] == 1
    assert result["sources"][0]["status"] == "access_blocked"
    assert result["sources"][0]["http_status"] == 403
    assert "HTTP 403" in result["sources"][0]["error"]
    assert doc.file_hash == "old"
    service.replace.assert_not_awaited()
