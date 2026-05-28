"""Tests du filtre RH et du parsing du service JORF (fond LODA Légifrance)."""

from app.rag.norme_hierarchy import DOCUMENT_TYPE_HIERARCHY
from app.services.jorf_service import (
    _CODE_SECU_ID,
    _CODE_TRAVAIL_ID,
    _NATURE_TO_SOURCE_TYPE,
    JorfService,
    _is_rh_relevant,
    _normalize,
    _title_matches_keywords,
)


# --- _normalize --------------------------------------------------------------

def test_normalize_strips_accents_and_lowercases():
    assert _normalize("Décret RELATIF à la Prévention") == "decret relatif a la prevention"


# --- _title_matches_keywords -------------------------------------------------

def test_title_keywords_match_duerp_law():
    title = (
        "LOI n° 2026-123 relative au document unique d'évaluation des "
        "risques professionnels (DUERP)"
    )
    assert _title_matches_keywords(title) is True


def test_title_keywords_match_accent_insensitive():
    # "prévention des risques" avec accents doit matcher la clé sans accent
    assert _title_matches_keywords("Décret relatif à la prévention des risques") is True


def test_title_keywords_reject_nomination():
    title = "Arrêté du 12 mai 2026 portant nomination au conseil d'administration de l'INRAE"
    assert _title_matches_keywords(title) is False


# --- _is_rh_relevant (filtre mixte) ------------------------------------------

def test_relevant_when_modifies_code_travail_even_without_keyword():
    # Titre sans mot-clé RH mais le texte modifie le Code du travail → gardé
    assert _is_rh_relevant("Décret n° 2026-1 portant diverses mesures", {_CODE_TRAVAIL_ID}) is True


def test_relevant_when_modifies_code_secu():
    assert _is_rh_relevant("Décret technique", {_CODE_SECU_ID}) is True


def test_relevant_when_keyword_even_without_code_link():
    assert _is_rh_relevant("Loi relative au télétravail", set()) is True


def test_irrelevant_when_no_keyword_and_no_code_link():
    assert _is_rh_relevant("Arrêté portant nomination d'un préfet", set()) is False


# --- mapping nature → source_type --------------------------------------------

def test_nature_mapping_targets_existing_hierarchy_types():
    assert _NATURE_TO_SOURCE_TYPE == {
        "LOI": "loi",
        "ORDONNANCE": "ordonnance",
        "DECRET": "decret",
        "ARRETE": "arrete",
    }
    for source_type in _NATURE_TO_SOURCE_TYPE.values():
        assert source_type in DOCUMENT_TYPE_HIERARCHY


# --- _parse_search_result ----------------------------------------------------

def test_parse_search_result_from_titles_array():
    raw = {
        "titles": [{"cid": "JORFTEXT000099", "title": "LOI relative au travail"}],
        "nature": "loi",
    }
    cid, title, nature = JorfService._parse_search_result(raw)
    assert cid == "JORFTEXT000099"
    assert title == "LOI relative au travail"
    assert nature == "LOI"


def test_parse_search_result_from_flat_fields():
    raw = {"id": "JORFTEXT000100", "title": "Décret salarié", "nature": "decret"}
    cid, title, nature = JorfService._parse_search_result(raw)
    assert cid == "JORFTEXT000100"
    assert nature == "DECRET"


# --- _parse_consult ----------------------------------------------------------

def test_parse_consult_detects_code_link_and_concatenates_articles():
    consult = {
        "liens": [{"cidTexte": _CODE_TRAVAIL_ID}],
        "articles": [
            {"num": "1", "content": "Premier article."},
            {"num": "2", "content": "Second article."},
        ],
        "datePublication": "2026-05-20",
    }
    text, code_ids, pub = JorfService._parse_consult(consult)
    assert _CODE_TRAVAIL_ID in code_ids
    assert "Premier article." in text
    assert "Second article." in text
    assert pub is not None
    assert (pub.year, pub.month, pub.day) == (2026, 5, 20)


def test_parse_consult_handles_epoch_millis_date():
    consult = {"liens": [], "articles": [{"content": "x" * 60}], "datePublication": 1747699200000}
    _text, _code_ids, pub = JorfService._parse_consult(consult)
    assert pub is not None


# --- run_jorf_sync écrit un SyncLog ------------------------------------------

async def test_run_jorf_sync_writes_synclog(monkeypatch):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.sync_log import SyncLog
    from app.services.jorf_service import JorfSyncResult
    from tests.conftest import test_session_factory

    async def fake_sync(self, db, user_id, **kwargs):
        return JorfSyncResult(
            total_fetched=5, new_ingested=2, filtered_out=1, already_exists=0, errors=0
        )

    monkeypatch.setattr(
        "app.services.jorf_service.JorfService.sync", fake_sync, raising=True
    )

    from app.worker import run_jorf_sync

    await run_jorf_sync({"session_factory": test_session_factory}, str(_uuid.uuid4()))

    async with test_session_factory() as db:
        rows = (
            await db.execute(select(SyncLog).where(SyncLog.sync_type == "jorf"))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].items_created == 2
    assert rows[0].items_fetched == 5
