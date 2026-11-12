"""La synchro des conventions met à jour la version PARTAGÉE, jamais une copie.

Avant le 12/11/2026, la synchro hebdomadaire cherchait une copie propre à
chaque organisation, n'en trouvait pas (l'installation crée des documents
partagés) et en fabriquait une à chaque passage : doublons dans les réponses
et version partagée jamais rafraîchie.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.models.ccn import CcnReference, OrganisationConvention
from app.models.document import Document
from app.models.organisation import Organisation
from app.services import kali_service as kali_module
from app.services.kali_service import KaliService
from tests.conftest import test_session_factory as session_factory

IDCC = "0413"

ARTICLES = [
    {"num": "1", "content": "Champ d'application", "category": "base", "section": ""},
    {"num": "2", "content": "Prime de vie chère", "category": "accord", "section": ""},
]


@pytest.fixture
async def installed(monkeypatch):
    """An organisation with IDCC 0413 installed and its shared snapshot."""
    service = KaliService()
    parts, snapshot_hash = service._common_doc_parts(
        ARTICLES, CcnReference(idcc=IDCC, titre="Handicapés", titre_court="Handicapés")
    )
    async with session_factory() as db:
        org = Organisation(name="Org")
        db.add(org)
        db.add(CcnReference(idcc=IDCC, titre="Handicapés", titre_court="Handicapés", kali_id="K"))
        await db.flush()
        db.add(OrganisationConvention(organisation_id=org.id, idcc=IDCC, status="ready"))
        old = Document(
            name=f"CCN Handicapés (IDCC {IDCC})",
            source_type="convention_collective_nationale",
            storage_path=f"common/ccn/{IDCC}/old.txt",
            file_hash=snapshot_hash,
            indexation_status="indexed",
            chunk_count=3,
        )
        db.add(old)
        await db.commit()
        old_id = str(old.id)

    monkeypatch.setattr(
        KaliService, "_fetch_kali_articles", AsyncMock(return_value=(ARTICLES, [], "2026-11-01"))
    )
    monkeypatch.setattr(kali_module, "enqueue_ingestion", AsyncMock())
    cleanup = AsyncMock()
    monkeypatch.setattr(KaliService, "_enqueue_old_docs_cleanup", cleanup)
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: Mock())
    return service, old_id, cleanup


async def _ccn_documents(db) -> list[Document]:
    return list(
        (
            await db.execute(
                select(Document).where(
                    Document.source_type.in_(["convention_collective_nationale", "accord_branche"])
                )
            )
        ).scalars()
    )


async def test_unchanged_snapshot_writes_nothing(installed):
    service, old_id, cleanup = installed
    async with session_factory() as db:
        result = await service.bulk_sync_ccn(db, [IDCC], uuid.uuid4())
        docs = await _ccn_documents(db)
        org_conv = (await db.execute(select(OrganisationConvention))).scalar_one()

    assert result.skipped_identical == 1 and result.updates_needed == 0
    assert [str(d.id) for d in docs] == [old_id]
    assert org_conv.last_synced_at is not None
    cleanup.assert_not_awaited()


async def test_changed_snapshot_replaces_the_shared_documents_never_a_private_copy(
    installed, monkeypatch
):
    service, old_id, cleanup = installed
    changed = [*ARTICLES, {**ARTICLES[0], "num": "3", "content": "Nouvel article"}]
    monkeypatch.setattr(
        KaliService, "_fetch_kali_articles", AsyncMock(return_value=(changed, [], "2026-11-12"))
    )
    async with session_factory() as db:
        result = await service.bulk_sync_ccn(db, [IDCC], uuid.uuid4())
        docs = await _ccn_documents(db)
        org_conv = (await db.execute(select(OrganisationConvention))).scalar_one()

    assert result.updates_needed == 1
    assert all(d.organisation_id is None for d in docs)
    assert all(d.storage_path.startswith("common/") for d in docs)
    new = [d for d in docs if str(d.id) != old_id]
    assert {d.source_type for d in new} == {"convention_collective_nationale", "accord_branche"}
    cleanup.assert_awaited_once_with([old_id])
    assert org_conv.source_date == "2026-11-12"


async def test_partial_fetch_never_replaces_a_complete_snapshot(installed, monkeypatch):
    service, old_id, cleanup = installed
    monkeypatch.setattr(
        KaliService,
        "_fetch_kali_articles",
        AsyncMock(return_value=(ARTICLES[:1], ["Texte KALITEXT1 introuvable"], None)),
    )
    async with session_factory() as db:
        result = await service.bulk_sync_ccn(db, [IDCC], uuid.uuid4())
        docs = await _ccn_documents(db)

    assert result.errors == 1
    assert [str(d.id) for d in docs] == [old_id]
    cleanup.assert_not_awaited()


async def test_forced_refresh_rebuilds_an_unchanged_snapshot(installed):
    service, old_id, cleanup = installed
    async with session_factory() as db:
        result = await service.refresh_common_ccn(db, IDCC, uuid.uuid4(), force=True)
    assert result.update_needed
    cleanup.assert_awaited_once_with([old_id])
