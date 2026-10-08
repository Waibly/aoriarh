import json
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.boss_service import BossService, BossSyncResult


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [True, False])
async def test_changed_or_new_body_only_archived(existing):
    doc = SimpleNamespace(id=uuid.uuid4(), file_hash="old", source_url="old", source_updated_date=None)
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=doc if existing else None))), commit=AsyncMock(), add=Mock())
    storage = Mock()
    result = BossSyncResult()
    notes = [{"url": "https://boss.gouv.fr/notice", "source_html": "Projet applicable au 1er janvier 2027"}]
    await BossService()._upsert_document(db, storage, uuid.uuid4(), "/portail/accueil/bulletin-de-paie/montant-net-social.html", "Paie", "<h1>MNS</h1>Mis à jour le 02/10/2026", "New source body", result, version_notes=notes)
    assert doc.file_hash == "old"
    assert doc.source_url == "old"
    db.commit.assert_not_awaited()
    db.add.assert_not_called()
    assert result.docs_pending == 1
    assert result.docs_created == result.docs_updated == 0
    assert storage.put_file_bytes.call_count == 2
    for call in storage.put_file_bytes.call_args_list:
        assert call.args[0].startswith("common/boss_review/")
        payload = json.loads(call.args[1])
        assert payload["version_notes"] == notes
        assert payload["source_updated_date"] == "2026-10-02"
        assert payload["automatic_ingestion"] is False
        assert "New source body" in payload["candidate_markdown"]


@pytest.mark.asyncio
async def test_unchanged_body_only_refreshes_metadata():
    import hashlib
    service = BossService()
    path = "/portail/accueil/controle.html"
    sha = hashlib.sha256(service._format_markdown("Test", "Contrôle", path, "body").encode()).hexdigest()
    doc = SimpleNamespace(file_hash=sha)
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=doc))), commit=AsyncMock())
    storage = Mock()
    result = BossSyncResult()
    await service._upsert_document(db, storage, uuid.uuid4(), path, "Contrôle", "<h1>Test</h1>Mis à jour au 02/10/2026", "body", result)
    assert result.docs_unchanged == 1
    assert doc.file_hash == sha
    storage.put_file_bytes.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_version_notes_keep_official_linked_source():
    service = BossService()
    service._fetch = AsyncMock(return_value="Original future publication")
    html = '<div class="bloc_notes_version"><a href="/portail/accueil/actualites-boss-et-rescrits/test.html">Note</a><a href="https://evil.example/portail/accueil/actualites-boss-et-rescrits/test.html">External</a></div>'
    notes = await service._fetch_version_notes(Mock(), html)
    assert len(notes) == 1
    assert notes[0]["source_html"] == "Original future publication"
    service._fetch.assert_awaited_once()


@pytest.mark.parametrize("text, expected", [("Mis à jour le 02/10/2026", date(2026,10,2)), ("À jour au 01/10/2026", date(2026,10,1)), ("Mis à jour le 32/10/2026", None)])
def test_source_dates(text, expected):
    assert BossService._parse_a_jour_date(text) == expected
