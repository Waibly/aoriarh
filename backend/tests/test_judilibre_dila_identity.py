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
async def test_judilibre_withdrawal_audit_does_not_treat_dila_absence_as_withdrawal():
    async with test_session_factory() as db:
        db.add_all(
            [
                doc("00-12431", "2002-01-31"),
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
