"""ANI kept up to date, and case-law dates never invented (Nov. 2026 audit).

ANI: every text still applicable is ingested whatever its year (1969, 2008…);
a text changed in KALI is reingested; an abrogated one leaves the corpus, but
only when the KALI list was read completely.
Case law: no « today » date for a Cassation decision without date; the
Conseil constitutionnel « 1er octobre » and official dates are read; the
paused CA collection schedules nothing.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.models.document import Document
from app.services import kali_service as kali_module
from app.services.conseil_constit_service import ConseilConstitService
from app.services.document_service import DocumentService
from app.services.judilibre_service import JudilibreService
from app.services.kali_service import KaliService
from tests.conftest import test_session_factory as session_factory

ARTICLES = [{"num": "1", "content": "Texte de l'accord", "section": ""}]


def _cand(kali_id: str, title: str, etat: str = "VIGUEUR_ETEN") -> dict:
    return {
        "id": kali_id,
        "title": title,
        "etat": etat,
        "year": 1969,
        "signature_date": date(1969, 2, 10),
    }


def _ani_doc(kali_id: str, text: str) -> Document:
    return Document(
        name=f"ANI {kali_id}",
        source_type="accord_national_interprofessionnel",
        storage_path=f"common/ani/{kali_id}.txt",
        file_hash=hashlib.sha256(text.encode()).hexdigest(),
        indexation_status="indexed",
        chunk_count=2,
        numero_pourvoi=kali_id,
    )


@pytest.fixture
def kali(monkeypatch):
    service = KaliService()
    monkeypatch.setattr(kali_module, "_API_THROTTLE", 0)
    monkeypatch.setattr(kali_module, "enqueue_ingestion", AsyncMock())
    monkeypatch.setattr(service, "_api_post", AsyncMock(return_value={"text": "x"}))
    monkeypatch.setattr(service, "_extract_articles_from_text", Mock(return_value=ARTICLES))
    cleanup = AsyncMock()
    monkeypatch.setattr(KaliService, "_enqueue_old_docs_cleanup", cleanup)
    vectors = Mock()
    monkeypatch.setattr(KaliService, "_delete_document_vectors", vectors)
    monkeypatch.setattr("app.services.storage_service.StorageService", lambda: Mock())

    async def delete_row(self, doc_id):
        await self.db.delete(await self.db.get(Document, doc_id))
        await self.db.commit()

    monkeypatch.setattr(DocumentService, "delete_common_document", delete_row)
    return service, cleanup, vectors


async def _ani_ids(db) -> list[str]:
    rows = await db.execute(
        select(Document.numero_pourvoi).where(
            Document.source_type == "accord_national_interprofessionnel"
        )
    )
    return sorted(r[0] for r in rows)


async def test_old_applicable_ani_is_ingested(kali, monkeypatch):
    service, cleanup, _ = kali
    title = "Accord national interprofessionnel du 10 février 1969 relatif à l'emploi"
    monkeypatch.setattr(
        service, "_search_ani", AsyncMock(return_value=([_cand("KALITEXT1969", title)], True))
    )
    async with session_factory() as db:
        result = await service.sync_ani(db, uuid.uuid4())
        assert await _ani_ids(db) == ["KALITEXT1969"]
    assert result.created == 1
    cleanup.assert_not_awaited()


async def test_unchanged_ani_is_skipped_and_changed_one_replaced(kali, monkeypatch):
    service, cleanup, _ = kali
    same_title, changed_title = "ANI A", "ANI B"
    same_text = KaliService._format_ani_as_markdown(ARTICLES, same_title)
    async with session_factory() as db:
        db.add_all([_ani_doc("KA", same_text), _ani_doc("KB", "ancienne version")])
        await db.commit()
        old_b = (
            await db.execute(select(Document.id).where(Document.numero_pourvoi == "KB"))
        ).scalar_one()
    monkeypatch.setattr(
        service,
        "_search_ani",
        AsyncMock(return_value=([_cand("KA", same_title), _cand("KB", changed_title)], True)),
    )
    async with session_factory() as db:
        result = await service.sync_ani(db, uuid.uuid4())
    assert (result.skipped, result.updated, result.created) == (1, 1, 0)
    cleanup.assert_awaited_once()
    assert cleanup.await_args.args[0] == [str(old_b)]
    assert len(cleanup.await_args.kwargs["replacement_ids"]) == 1


async def test_abrogated_ani_leaves_the_corpus(kali, monkeypatch):
    service, _, vectors = kali
    async with session_factory() as db:
        db.add(_ani_doc("KOLD", "texte"))
        await db.commit()
    monkeypatch.setattr(
        service, "_search_ani", AsyncMock(return_value=([_cand("KOLD", "ANI", "ABROGE")], True))
    )
    async with session_factory() as db:
        result = await service.sync_ani(db, uuid.uuid4())
        assert await _ani_ids(db) == []
    assert result.removed == 1
    vectors.assert_called_once()


async def test_nothing_removed_when_the_list_is_incomplete(kali, monkeypatch):
    service, _, vectors = kali
    async with session_factory() as db:
        db.add(_ani_doc("KOLD", "texte"))
        await db.commit()
    monkeypatch.setattr(
        service, "_search_ani", AsyncMock(return_value=([_cand("KOLD", "ANI", "ABROGE")], False))
    )
    async with session_factory() as db:
        result = await service.sync_ani(db, uuid.uuid4())
        assert await _ani_ids(db) == ["KOLD"]
    assert result.removed == 0 and result.errors == 1
    vectors.assert_not_called()


async def test_ani_kept_when_its_vectors_cannot_be_deleted(kali, monkeypatch):
    service, _, vectors = kali
    vectors.side_effect = RuntimeError("qdrant down")
    async with session_factory() as db:
        db.add(_ani_doc("KOLD", "texte"))
        await db.commit()
    monkeypatch.setattr(
        service, "_search_ani", AsyncMock(return_value=([_cand("KOLD", "ANI", "PERIME")], True))
    )
    async with session_factory() as db:
        result = await service.sync_ani(db, uuid.uuid4())
        assert await _ani_ids(db) == ["KOLD"]
    assert result.removed == 0 and result.errors == 1


def test_cassation_decision_without_date_is_rejected():
    raw = {"text": "Arrêt", "decision_date": "", "number": "24-10.000", "chamber": "soc"}
    assert JudilibreService._parse_decision(raw) is None


def test_conseil_constit_reads_first_of_month_and_official_date():
    title = "Décision 2026-329 L - 1er octobre 2026 - Nature juridique"
    assert ConseilConstitService._parse_date_from_title(title) == date(2026, 10, 1)
    assert ConseilConstitService._official_date({"dateTexte": 1790812800000}) == date(2026, 10, 1)
    assert ConseilConstitService.display_name(title, "l", date(2026, 10, 1)) == (
        "Cons. const., 01/10/2026, n° 2026-329 L"
    )


async def test_paused_ca_collection_schedules_nothing(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "judilibre_ca_collection_enabled", False)
    schedule = AsyncMock()
    monkeypatch.setattr("app.services.judilibre_ca_sync.schedule_scan", schedule)
    db = Mock(commit=AsyncMock())
    result = await JudilibreService().sync_ca_chambre_sociale(db, uuid.uuid4())
    assert result.complete
    schedule.assert_not_awaited()
    db.commit.assert_not_awaited()
