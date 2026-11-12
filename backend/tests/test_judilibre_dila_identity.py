import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.models.document import Document
from app.services.judilibre_service import JudilibreService
from tests.conftest import test_session_factory


def doc(number, day, path="common/dila/cass/source.xml"):
    return Document(
        name="Source publique",
        source_type="arret_cour_cassation",
        chambre="Chambre sociale",
        juridiction="Cour de cassation",
        organisation_id=None,
        storage_path=path,
        numero_pourvoi=number,
        date_decision=date.fromisoformat(day),
        indexation_status="indexed",
    )


def service():
    result = JudilibreService()
    result._client_id = result._client_secret = "test"
    return result


def raw(number, day, identifier, chamber="soc"):
    return dict(
        number=number,
        decision_date=day,
        id=identifier,
        chamber=chamber,
        jurisdiction="cc",
        publication=["b"],
        text="Texte source intégral.",
    )


@pytest.mark.asyncio
async def test_social_sync_recognizes_dila_aliases_and_preserves_different_dates(monkeypatch):
    async with test_session_factory() as db:
        db.add_all([doc("00-12431", "2002-01-31"), doc("14-27266 et autres", "2016-07-06")])
        await db.commit()
        instance = service()
        items = [
            raw("00-12.431", "2002-01-31", "a" * 24),
            raw("14-27.266", "2016-07-06", "b" * 24),
            raw("00-12.431", "2003-01-31", "c" * 24),
            raw("00-12.431", "2003-01-31", "c" * 24),
            raw("01-12.999", "2004-01-31", "d" * 24, chamber="cr"),
        ]
        instance._api_get = AsyncMock(return_value=dict(results=items, total=5))
        instance._create_document = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        enqueue = AsyncMock()
        monkeypatch.setattr("app.services.judilibre_service.enqueue_ingestion", enqueue)
        monkeypatch.setattr("app.services.storage_service.StorageService", Mock())
        result = await instance.sync(db, uuid.uuid4())
        assert (result.new_ingested, result.already_exists, result.filtered_out, result.errors) == (
            1,
            3,
            1,
            0,
        )
        assert instance._create_document.await_count == enqueue.await_count == 1
        assert instance._create_document.call_args.kwargs["source_url"] == (
            "https://www.courdecassation.fr/decision/" + "c" * 24
        )


@pytest.mark.asyncio
async def test_enqueue_failure_cannot_create_another_copy_in_the_same_batch(monkeypatch):
    instance = service()
    item = raw("24-12.345", "2026-10-20", "a" * 24)
    instance._api_get = AsyncMock(return_value=dict(results=[item, item], total=2))
    instance._create_document = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(
        "app.services.judilibre_service.enqueue_ingestion",
        AsyncMock(side_effect=RuntimeError("queue unavailable")),
    )
    monkeypatch.setattr("app.services.storage_service.StorageService", Mock())
    async with test_session_factory() as db:
        result = await instance.sync(db, uuid.uuid4())
    assert result.errors == 1 and result.already_exists == 1
    assert instance._create_document.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["common/dila/cass/", "common/dila/inca/"])
async def test_judilibre_withdrawal_audit_does_not_treat_dila_absence_as_withdrawal(prefix):
    async with test_session_factory() as db:
        db.add_all(
            [
                doc("00-12431", "2002-01-31", prefix + "source.xml"),
                doc("24-12.345", "2026-10-20", "common/judilibre/source.txt"),
            ]
        )
        await db.commit()
        instance = service()
        instance._api_get = AsyncMock(return_value=dict(results=[dict(number="24-12.345")]))
        result = await instance.find_deleted_decisions(db)
        assert result.checked == result.present == 1
        assert not result.gone
        assert instance._api_get.await_count == 1


@pytest.mark.asyncio
async def test_presence_check_survives_an_upstream_error_on_one_decision():
    """2026-11-01: one Judilibre 500 aborted the whole monthly presence check."""
    import httpx

    async with test_session_factory() as db:
        db.add_all(
            [
                doc("24-21.567", "2026-10-20", "common/judilibre/a.txt"),
                doc("24-12.345", "2026-10-21", "common/judilibre/b.txt"),
            ]
        )
        await db.commit()
        instance = service()
        request = httpx.Request("GET", "https://api.piste.gouv.fr/x")
        upstream_500 = httpx.HTTPStatusError(
            "500", request=request, response=httpx.Response(500, request=request)
        )
        instance._api_get = AsyncMock(
            side_effect=[upstream_500, dict(results=[dict(number="24-12.345")])]
        )
        result = await instance.find_deleted_decisions(db)
    assert result.checked == 2
    assert result.present == 1 and result.unknown == 1
    assert not result.gone


@pytest.mark.asyncio
async def test_api_get_retries_transient_server_errors(monkeypatch):
    import httpx

    monkeypatch.setattr("app.services.judilibre_service.asyncio.sleep", AsyncMock())
    instance = service()
    instance._get_access_token = AsyncMock(return_value="t")
    responses = iter([500, 502, 200])

    def handler(request):
        code = next(responses)
        return httpx.Response(code, json={"results": []} if code == 200 else None)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        data = await instance._api_get(client, "/search", {"query": "x"})
    assert data == {"results": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 416])
async def test_strict_source_fetch_keeps_the_original_http_failure(monkeypatch, status):
    import httpx

    monkeypatch.setattr("app.services.judilibre_service.asyncio.sleep", AsyncMock())
    instance = service()
    instance._get_access_token = AsyncMock(return_value="t")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await instance._api_get(client, "/decision", {"id": "a" * 24}, strict=True)
        assert caught.value.response.status_code == status
        assert await instance._api_get(client, "/decision", {"id": "a" * 24}) is None


@pytest.mark.asyncio
async def test_strict_source_timeout_remains_a_timeout_after_bounded_retries(monkeypatch):
    import httpx

    monkeypatch.setattr("app.services.judilibre_service.asyncio.sleep", AsyncMock())
    instance = service()
    instance._get_access_token = AsyncMock(return_value="t")
    calls = 0

    def timeout(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("transport timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(httpx.ReadTimeout):
            await instance._api_get(client, "/decision", {"id": "a" * 24}, strict=True)
    assert calls == 3
