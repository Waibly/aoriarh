import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.social_ca_service import SocialCaService, admitted, PREFIX
from app.services.judilibre_service import JudilibreService

A = "a" * 24
B = "b" * 24
C = "c" * 24
META = {
    "id": A,
    "jurisdiction": "ca",
    "nac": "80J",
    "decision_date": "2026-10-01",
    "number": "25/12345",
    "location": "ca_paris",
    "chamber": "Pôle social",
}


@pytest.mark.parametrize(
    "nac,expected",
    [
        ("80J", True),
        ("81A", True),
        ("84E", True),
        ("89B", True),
        ("88E", False),
        ("89H", False),
        ("14G", False),
        ("80UNKNOWN", False),
        (None, False),
    ],
)
def test_official_scope_is_explicit_not_keyword_based(nac, expected):
    assert admitted(dict(META, nac=nac)) is expected
    assert not admitted(dict(META, nac=nac, jurisdiction="cc"))


def service_with_memory(responses):
    service = SocialCaService(Mock(), api=Mock())
    memory = {}
    service.archive.read_json = lambda key: copy.deepcopy(memory.get(key))
    service.archive.save_json = lambda key, value: memory.__setitem__(key, copy.deepcopy(value))
    service.api._api_get = AsyncMock(side_effect=responses)
    service.api._parse_decision = JudilibreService._parse_decision
    return service, memory


@pytest.mark.asyncio
async def test_complete_inventory_keeps_non_social_records_without_ingestion():
    service, memory = service_with_memory(
        [{"total": 2, "results": [META, dict(META, id=B, nac="14G")], "next_batch": None}]
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))), add=Mock()
    )
    result = await service.sync(db, apply=False, today=date(2026, 10, 8))
    assert result["inventoried"] == 2 and result["eligible"] == 1
    assert result["review_pending"] == 1
    assert result["created"] == 0
    assert result["remaining_eligible"] == 1
    inventory = next(v for k, v in memory.items() if "/inventories/" in k)
    assert set(inventory) == {A, B}
    db.add.assert_not_called()
    params = service.api._api_get.call_args.kwargs["params"]
    assert params["date_type"] == "update" and params["abridged"] == "true"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"total": 2, "results": [META], "next_batch": None},
        {"total": 2, "results": [META, META], "next_batch": None},
        {"total": "2", "results": [META], "next_batch": None},
    ],
)
async def test_incomplete_or_duplicate_inventory_never_admits(response):
    service, memory = service_with_memory([response])
    db = Mock()
    with pytest.raises(ValueError):
        await service.sync(db, today=date(2026, 10, 8))
    db.add.assert_not_called()
    assert not memory


@pytest.mark.asyncio
async def test_cursor_progress_and_total_are_verified():
    service, memory = service_with_memory(
        [
            {
                "total": 2,
                "results": [META],
                "next_batch": "https://ignored.example/scan?searchAfter=cursor",
            },
            {"total": 2, "results": [dict(META, id=B)], "next_batch": None},
        ]
    )
    records = await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert set(records) == {A, B}
    assert service.api._api_get.call_args.kwargs["params"]["searchAfter"] == "cursor"


@pytest.mark.asyncio
async def test_retired_decision_is_not_reintroduced():
    service, memory = service_with_memory([{"total": 1, "results": [META], "next_batch": None}])
    doc = SimpleNamespace(
        private_dossier_id=None,
        private_conversation_id=None,
        retired_at="retired",
        indexation_status="indexed",
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[doc]))), add=Mock()
    )
    result = await service.sync(db, today=date(2026, 10, 8))
    assert result["created"] == 0 and result["review_pending"] == 1
    assert service.api._api_get.await_count == 1
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_daily_budget_survives_multiple_runs(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "social_ca_max_documents_per_day", 20)
    monkeypatch.setattr(settings, "social_ca_max_tokens_per_day", 250_000)
    service, memory = service_with_memory([{"total": 1, "results": [META], "next_batch": None}])
    memory[PREFIX + "budgets/2026-10-08.json"] = {
        "tokens_reserved": 250000,
        "documents_reserved": 20,
    }
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))), add=Mock()
    )
    result = await service.sync(db, today=date(2026, 10, 8))
    assert result["created"] == 0 and result["budget_pending"] == 1
    assert result["remaining_eligible"] == 1
    assert service.api._api_get.await_count == 1
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_source_category_change_prevents_publication():
    service, memory = service_with_memory(
        [
            {"total": 1, "results": [META], "next_batch": None},
            dict(META, nac="14G", text="Official source"),
        ]
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))),
        add=Mock(),
        rollback=AsyncMock(),
    )
    result = await service.sync(db, today=date(2026, 10, 8))
    assert result["errors"] and result["created"] == 0
    assert result["daily_tokens_reserved"] == 0
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_changed_existing_decision_is_archived_without_overwriting():
    service, memory = service_with_memory(
        [
            {"total": 1, "results": [META], "next_batch": None},
            dict(META, text="Updated official source"),
        ]
    )
    doc = SimpleNamespace(
        private_dossier_id=None,
        private_conversation_id=None,
        retired_at=None,
        indexation_status="indexed",
        file_hash="old",
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[doc]))), add=Mock()
    )
    result = await service.sync(db, today=date(2026, 10, 8))
    assert result["review_pending"] == 1 and result["created"] == 0
    assert doc.file_hash == "old"
    assert any("/revisions/" in key for key in memory)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_status_is_admin_only(client, manager_user):
    response = await client.get(
        "/api/v1/admin/syncs/social-ca/status",
        headers={"Authorization": "Bearer " + manager_user["token"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_new_admission_reserves_budget_before_embedding(monkeypatch):
    body = "Texte officiel de la décision."
    service, memory = service_with_memory(
        [
            {"total": 1, "results": [META], "next_batch": None},
            dict(META, text=body),
        ]
    )
    doc_holder = []
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))),
        add=lambda doc: doc_holder.append(doc),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )
    pipeline = Mock()
    pipeline.jurisprudence_chunker.chunk.return_value = [body]
    pipeline._build_jurisprudence_header.return_value = ""

    async def ingest(*args, **kwargs):
        budget = memory[PREFIX + "budgets/2026-10-08.json"]
        assert budget["documents_reserved"] == 1
        assert budget["tokens_reserved"] == kwargs["max_embedding_tokens"] > 0
        doc_holder[0].indexation_status = "indexed"
        doc_holder[0].chunk_count = 1

    pipeline.ingest = AsyncMock(side_effect=ingest)
    monkeypatch.setattr("app.rag.ingestion.IngestionPipeline", lambda: pipeline)
    service.archive.storage.get_file_bytes_bounded.return_value = body.encode()
    result = await service.sync(db, today=date(2026, 10, 8))
    assert result["created"] == 1 and not result["errors"]
    assert result["remaining_eligible"] == 0
    assert doc_holder[0].source_type == "arret_cour_appel"
    assert doc_holder[0].organisation_id is None
    pipeline.ingest.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('limit_kind', ['documents', 'tokens', 'details'])
async def test_internal_limits_defer_without_paid_call(monkeypatch, limit_kind):
    from app.core.config import settings

    service, memory = service_with_memory([
        {'total': 1, 'results': [META], 'next_batch': None},
    ])
    monkeypatch.setattr(settings, 'social_ca_max_documents_per_day', 200)
    monkeypatch.setattr(settings, 'social_ca_max_tokens_per_day', 2_000_000)
    if limit_kind == 'details':
        # An existing decision uses the one allowed detail check first.
        service.api._api_get.side_effect = [
            {'total': 2, 'results': [dict(META, id=B), META], 'next_batch': None},
            dict(META, id=B, text='current'),
        ]
        monkeypatch.setattr(settings, 'social_ca_max_detail_checks', 1)
        import hashlib
        doc = SimpleNamespace(private_dossier_id=None, private_conversation_id=None,
                              retired_at=None, indexation_status='indexed',
                              file_hash=hashlib.sha256(b'current').hexdigest())
        db = SimpleNamespace(scalars=AsyncMock(side_effect=[
            Mock(all=Mock(return_value=[doc])), Mock(all=Mock(return_value=[])),
            Mock(all=Mock(return_value=[])),
        ]), add=Mock())
    else:
        memory[PREFIX + 'budgets/2026-10-11.json'] = {
            'documents_reserved': 200 if limit_kind == 'documents' else 20,
            'tokens_reserved': 2_000_000 if limit_kind == 'tokens' else 100_420,
        }
        db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))),
                             add=Mock())
    result = await service.sync(db, today=date(2026, 10, 11))
    assert result['created'] == 0 and not result['errors']
    assert result['remaining_eligible'] == result['budget_pending'] == 1
    assert result['limits']['documents_per_day'] == 200
    assert result['limits']['estimated_tokens_per_day'] == 2_000_000
    db.add.assert_not_called()
    assert A in memory[PREFIX + 'state.json']['pending']


@pytest.mark.asyncio
async def test_raised_budget_resumes_existing_daily_ledger(monkeypatch):
    from app.core.config import settings

    body = 'Texte officiel de la décision.'
    service, memory = service_with_memory([
        {'total': 1, 'results': [META], 'next_batch': None}, dict(META, text=body),
    ])
    ledger_key = PREFIX + 'budgets/2026-10-11.json'
    memory[ledger_key] = {'documents_reserved': 20, 'tokens_reserved': 100_420}
    monkeypatch.setattr(settings, 'social_ca_max_documents_per_day', 200)
    monkeypatch.setattr(settings, 'social_ca_max_tokens_per_day', 2_000_000)
    docs = []
    db = SimpleNamespace(scalars=AsyncMock(return_value=Mock(all=Mock(return_value=[]))),
                         add=docs.append, commit=AsyncMock(), refresh=AsyncMock(),
                         rollback=AsyncMock())
    pipeline = Mock()
    pipeline.jurisprudence_chunker.chunk.return_value = [body]
    pipeline._build_jurisprudence_header.return_value = ''

    async def ingest(*args, **kwargs):
        assert memory[ledger_key]['documents_reserved'] == 21
        assert memory[ledger_key]['tokens_reserved'] > 100_420
        docs[0].indexation_status = 'indexed'
        docs[0].chunk_count = 1

    pipeline.ingest = AsyncMock(side_effect=ingest)
    monkeypatch.setattr('app.rag.ingestion.IngestionPipeline', lambda: pipeline)
    service.archive.storage.get_file_bytes_bounded.return_value = body.encode()
    result = await service.sync(db, today=date(2026, 10, 11))
    assert result['created'] == 1 and result['remaining_eligible'] == 0
    assert not result['errors']
    assert result['daily_documents_reserved'] == 21
    pipeline.ingest.assert_awaited_once()


@pytest.mark.parametrize(
    "nac", ["80A", "80B", "80C", "80D", "80E", "80F", "80G", "80H", "80I",
            "80X", "82K", "83D", "83E", "83F", "84F", "84G", "84H", "84I", "87X"]
)
def test_historical_and_additional_official_employment_codes_remain_admitted(nac):
    assert admitted(dict(META, nac=nac, chamber="1re chambre"))


@pytest.mark.parametrize("nac", [None, "", [], {}, "88C", "89H", "80UNKNOWN", "14G"])
def test_ambiguous_sources_stay_in_review_without_keyword_admission(nac):
    from app.services.social_ca_scope import classify_ca_scope

    raw = dict(META, nac=nac, text="Contrat de travail, salaire, licenciement", chamber="Sociale")
    original = copy.deepcopy(raw)
    result = classify_ca_scope(raw)
    assert result["status"] == "review"
    assert result["reason"]
    assert raw == original
    assert not admitted(raw)


@pytest.mark.asyncio
async def test_inventory_completes_beyond_twenty_pages_without_any_admission():
    responses = [
        {"total": 23, "results": [dict(META, id=f"{n:024x}", nac="80A")],
         "next_batch": f"https://ignored.example/scan?searchAfter=cursor{n}" if n < 22 else None}
        for n in range(23)
    ]
    service, memory = service_with_memory(responses)
    records = await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert len(records) == 23
    assert service.api._api_get.await_count == 23
    assert not memory


@pytest.mark.asyncio
async def test_inventory_rejects_cursor_cycles_even_with_distinct_records():
    responses = [
        {"total": 4, "results": [dict(META, id=f"{n:024x}")],
         "next_batch": f"https://ignored.example/scan?searchAfter={cursor}"}
        for n, cursor in enumerate(["first", "second", "first"])
    ]
    service, memory = service_with_memory(responses)
    with pytest.raises(ValueError, match="cursor did not progress"):
        await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert not memory


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [True, False])
async def test_inventory_rejects_boolean_source_totals(total):
    service, memory = service_with_memory(
        [{"total": total, "results": [META], "next_batch": None}]
    )
    with pytest.raises(ValueError, match="inventory changed"):
        await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert not memory


@pytest.mark.asyncio
async def test_inventory_rejects_unexpected_source_jurisdiction_before_admission():
    service, memory = service_with_memory([
        {"total": 1, "results": [dict(META, jurisdiction="cc")], "next_batch": None}
    ])
    with pytest.raises(ValueError, match="Unexpected jurisdiction"):
        await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert not memory


@pytest.mark.asyncio
async def test_inventory_rejects_inverted_dates_without_request():
    service, memory = service_with_memory([])
    with pytest.raises(ValueError, match="date range"):
        await service.inventory(Mock(), date(2026, 10, 7), date(2026, 10, 1))
    service.api._api_get.assert_not_called()
    assert not memory


@pytest.mark.asyncio
async def test_inventory_rejects_continuation_after_claimed_total():
    service, memory = service_with_memory([
        {"total": 1, "results": [META],
         "next_batch": "https://ignored.example/scan?searchAfter=unexpected"}
    ])
    with pytest.raises(ValueError, match="total was exceeded"):
        await service.inventory(Mock(), date(2026, 10, 1), date(2026, 10, 7))
    assert not memory


@pytest.mark.parametrize("nac", ["86H", "86I"])
def test_codes_without_checked_publisher_mapping_remain_for_review(nac):
    from app.services.social_ca_scope import classify_ca_scope

    result = classify_ca_scope(dict(META, nac=nac))
    assert result["status"] == "review"
    assert result["reason"] == "nac_not_confirmed_in_checked_publisher_catalogue"
