"""Catalog, history and bounded BOCC retries; no external services."""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select

from app.models.bocc_issue import BoccIssue
from app.services.bocc_service import DILA_BASE_URL, BoccService, BoccSyncResult


def mock_http(monkeypatch, responses):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        status, text = responses.get(request.url.path, (404, ''))
        return httpx.Response(status, text=text)
    original = httpx.AsyncClient
    monkeypatch.setattr('app.services.bocc_service.httpx.AsyncClient',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return requests


@pytest.mark.asyncio
async def test_catalog_current_year_deduplicates_and_filters(monkeypatch):
    mock_http(monkeypatch, {
        '/OPENDATA/BOCC/FluxAnneeCourante/': (200,
            'CCO20260001.complet.taz CCO20260001.complet.taz '
            'CCO20260029.complet.taz CCO20250052.complet.taz'),
    })
    archives = await BoccService().discover_archives(2026)
    assert archives == {
        '20260001': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260001.complet.taz',
        '20260029': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260029.complet.taz',
    }


@pytest.mark.asyncio
async def test_catalog_annual_move_keeps_historical_url(monkeypatch):
    mock_http(monkeypatch, {
        '/OPENDATA/BOCC/2025/': (200, 'CCO20250052.complet.taz'),
        '/OPENDATA/BOCC/FluxAnneeCourante/': (200, 'CCO20250052.complet.taz'),
    })
    assert (await BoccService().discover_archives(2025))['20250052'] == (
        f'{DILA_BASE_URL}/2025/CCO20250052.complet.taz')


@pytest.mark.asyncio
async def test_catalog_server_error_is_not_empty_success(monkeypatch):
    mock_http(monkeypatch, {'/OPENDATA/BOCC/2026/': (503, 'unavailable')})
    with pytest.raises(httpx.HTTPStatusError):
        await BoccService().discover_archives(2026)


@pytest.mark.asyncio
async def test_download_uses_discovered_url_and_empty_extraction_fails(monkeypatch):
    requests = mock_http(monkeypatch, {
        '/OPENDATA/BOCC/FluxAnneeCourante/': (200, 'CCO20260029.complet.taz'),
        '/OPENDATA/BOCC/FluxAnneeCourante/CCO20260029.complet.taz': (200, 'bad archive'),
    })
    service = BoccService()
    monkeypatch.setattr(service, '_extract_individual_pdfs', lambda _: [])
    db = MagicMock()
    result = await service.process_issue(db, 2026, 29, uuid.uuid4())
    assert result.errors == 1 and not result.not_yet_available
    assert requests[-1].endswith('/FluxAnneeCourante/CCO20260029.complet.taz')
    db.add.assert_not_called()


def test_partial_failure_updates_same_history_row():
    db = MagicMock()
    issue = BoccIssue(numero='2026-01', year=2026, week=1,
                      status='error', avenants_ingested=2)
    result = BoccSyncResult(avenants_found=5, avenants_ingested=1,
                            errors=1, error_messages=['one PDF failed'])
    assert BoccService.record_result(db, issue, 2026, 1, result) is issue
    assert issue.status == 'error' and issue.avenants_ingested == 3
    BoccService.record_result(db, issue, 2026, 1, BoccSyncResult(avenants_found=5))
    assert issue.status == 'processed' and issue.error_message is None
    assert issue.avenants_ingested == 3


@pytest.mark.asyncio
async def test_daily_catalog_retries_old_error_skips_recent_and_success(admin_user, monkeypatch):
    from app import worker
    from tests.conftest import test_session_factory
    now = datetime.now(UTC)
    async with test_session_factory() as db:
        db.add_all([
            BoccIssue(numero='2026-01', year=2026, week=1, status='error',
                      processed_at=now-timedelta(days=3)),
            BoccIssue(numero='2026-02', year=2026, week=2, status='processed',
                      processed_at=now-timedelta(days=3)),
            BoccIssue(numero='2026-03', year=2026, week=3, status='error',
                      processed_at=now-timedelta(hours=1)),
        ])
        await db.commit()
    async def catalog(self, year):
        return {f'2026{n:04d}': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO2026{n:04d}.complet.taz'
                for n in (1, 2, 3, 29)} if year == 2026 else {}
    monkeypatch.setattr(BoccService, 'discover_archives', catalog)
    process = AsyncMock(return_value=BoccSyncResult(avenants_found=1))
    monkeypatch.setattr(BoccService, 'process_issue', process)
    monkeypatch.setattr(worker, '_create_sync_log', AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(worker, '_finish_sync_log', finish)
    await worker.run_daily_bocc_check({'session_factory': test_session_factory})
    assert [c.args[2] for c in process.call_args_list] == [29, 1]
    async with test_session_factory() as db:
        issues = (await db.execute(select(BoccIssue))).scalars().all()
        assert len(issues) == 4
        assert {r.numero:r.status for r in issues}['2026-01'] == 'processed'
    assert finish.call_args.kwargs['success'] is True


@pytest.mark.asyncio
async def test_daily_has_five_issue_limit(admin_user, monkeypatch):
    from app import worker
    from tests.conftest import test_session_factory
    async def catalog(self, year):
        return {f'2026{n:04d}': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO2026{n:04d}.complet.taz'
                for n in range(1, 11)} if year == 2026 else {}
    monkeypatch.setattr(BoccService, 'discover_archives', catalog)
    process = AsyncMock(return_value=BoccSyncResult(errors=1, error_messages=['network']))
    monkeypatch.setattr(BoccService, 'process_issue', process)
    monkeypatch.setattr(worker, '_create_sync_log', AsyncMock())
    monkeypatch.setattr(worker, '_finish_sync_log', AsyncMock())
    await worker.run_daily_bocc_check({'session_factory': test_session_factory})
    assert process.call_count == 5
    process.reset_mock()
    await worker.run_daily_bocc_check({'session_factory': test_session_factory})
    assert [c.args[2] for c in process.call_args_list] == [6, 7, 8, 9, 10]


@pytest.mark.asyncio
async def test_inventory_default_never_downloads_or_ingests(monkeypatch):
    from scripts.audit.prepare_bocc_inventory import prepare
    get = AsyncMock(side_effect=AssertionError('Unexpected HTTP download'))
    ingest = AsyncMock(side_effect=AssertionError('Unexpected ingestion'))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    monkeypatch.setattr('app.rag.tasks.enqueue_ingestion', ingest)
    result = await prepare([{
        'numero': '2026-01',
        'url': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260001.complet.taz',
    }], {'0413'})
    assert result['archives'][0]['status'] == 'not_downloaded'
    assert result['archives'][0]['documents_to_import'] is None
    get.assert_not_called()
    ingest.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_reuses_failed_row_and_does_not_record_missing_issue(monkeypatch):
    from tests.conftest import test_session_factory
    async with test_session_factory() as db:
        db.add(BoccIssue(numero='2026-01', year=2026, week=1, status='error',
                         processed_at=datetime.now(UTC)-timedelta(days=2)))
        await db.commit()
        service = BoccService()
        monkeypatch.setattr(service, 'discover_archives', AsyncMock(return_value={
            '20260001': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260001.complet.taz',
            '20260002': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260002.complet.taz',
        }))
        monkeypatch.setattr(service, 'process_issue', AsyncMock(side_effect=[
            BoccSyncResult(avenants_found=2), BoccSyncResult(not_yet_available=True),
        ]))
        result = await service.backfill_all(db, uuid.uuid4(), 2026, 2026)
        assert result.issues_processed == 1 and result.issues_skipped == 1
        rows = (await db.execute(select(BoccIssue))).scalars().all()
        assert len(rows) == 1 and rows[0].status == 'processed'


@pytest.mark.asyncio
async def test_collection_only_stores_review_manifest_even_without_idcc(monkeypatch):
    import json

    import pymupdf

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), 'Avenant du 15 octobre 2025\nNOR : ASET2650217M')
        raw = pdf.tobytes()
    mock_http(monkeypatch, {
        '/OPENDATA/BOCC/FluxAnneeCourante/CCO20260009.complet.taz': (200, 'archive'),
    })
    service = BoccService()
    monkeypatch.setattr(service, '_extract_individual_pdfs', lambda _: [('agreement.pdf', raw)])
    storage = MagicMock()
    monkeypatch.setattr('app.services.storage_service.StorageService', lambda: storage)
    queue = AsyncMock(side_effect=AssertionError('Indexation interdite pendant la veille'))
    monkeypatch.setattr('app.rag.tasks.enqueue_ingestion', queue)
    db = MagicMock()
    result = await service.process_issue(
        db, 2026, 9, uuid.uuid4(),
        archive_url=f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260009.complet.taz',
    )
    assert result.errors == 0 and result.avenants_ingested == 0
    assert result.review_manifest_path == 'common/bocc_review/2026-09/manifest.json'
    manifest = json.loads(storage.put_file_bytes.call_args.args[1])
    assert manifest['indexation_requested'] is False
    assert manifest['documents'][0]['nor'] == 'ASET2650217M'
    assert manifest['documents'][0]['idccs'] == []
    assert manifest['documents'][0]['admission'] == 'review_required'
    db.add.assert_not_called()
    db.execute.assert_not_called()
    queue.assert_not_called()
    issue = service.record_result(db, None, 2026, 9, result)
    assert issue.status == 'review_pending'


@pytest.mark.asyncio
async def test_branch_installation_cannot_admit_legacy_reserves(monkeypatch):
    db = MagicMock()
    queue = AsyncMock(side_effect=AssertionError('Indexation interdite'))
    monkeypatch.setattr('app.rag.tasks.enqueue_ingestion', queue)
    assert await BoccService().ingest_bocc_for_idcc(db, '1486') == 0
    db.execute.assert_not_called()
    queue.assert_not_called()


@pytest.mark.asyncio
async def test_pdf_failure_remains_in_manifest_without_admission(monkeypatch):
    import json

    mock_http(monkeypatch, {
        '/OPENDATA/BOCC/FluxAnneeCourante/CCO20260009.complet.taz': (200, 'archive'),
    })
    service = BoccService()
    monkeypatch.setattr(service, '_extract_individual_pdfs', lambda _: [('broken.pdf', b'bad')])
    storage = MagicMock()
    monkeypatch.setattr('app.services.storage_service.StorageService', lambda: storage)
    result = await service.process_issue(
        MagicMock(), 2026, 9, uuid.uuid4(),
        archive_url=f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260009.complet.taz',
    )
    manifest = json.loads(storage.put_file_bytes.call_args.args[1])
    assert result.errors == 1 and result.avenants_ingested == 0
    assert manifest['documents'][0]['metadata_status'] == 'error'
    assert manifest['documents'][0]['pdf'] == 'broken.pdf'


@pytest.mark.asyncio
async def test_review_pending_is_not_collected_again(admin_user, monkeypatch):
    from app import worker
    from tests.conftest import test_session_factory

    async with test_session_factory() as db:
        db.add(BoccIssue(numero='2026-09', year=2026, week=9, status='review_pending',
                         processed_at=datetime.now(UTC)-timedelta(days=5)))
        await db.commit()
    async def catalog(self, year):
        return {'20260009': f'{DILA_BASE_URL}/FluxAnneeCourante/CCO20260009.complet.taz'} \
            if year == 2026 else {}
    monkeypatch.setattr(BoccService, 'discover_archives', catalog)
    process = AsyncMock(side_effect=AssertionError('Already awaiting review'))
    monkeypatch.setattr(BoccService, 'process_issue', process)
    monkeypatch.setattr(worker, '_create_sync_log', AsyncMock())
    monkeypatch.setattr(worker, '_finish_sync_log', AsyncMock())
    await worker.run_daily_bocc_check({'session_factory': test_session_factory})
    process.assert_not_called()


@pytest.mark.asyncio
async def test_review_endpoint_requires_admin_and_valid_issue(
    client, admin_user, regular_user, monkeypatch,
):
    import json

    storage = MagicMock()
    storage.get_file_bytes_bounded.return_value = json.dumps({'documents': []}).encode()
    monkeypatch.setattr('app.services.storage_service.StorageService', lambda: storage)
    url = '/api/v1/admin/syncs/bocc/review?year=2026&week=9'
    assert (await client.get(url)).status_code in (401, 403)
    assert (await client.get(url, headers={
        'Authorization': f"Bearer {regular_user['token']}",
    })).status_code == 403
    storage.get_file_bytes_bounded.assert_not_called()
    headers = {'Authorization': f"Bearer {admin_user['token']}"}
    response = await client.get(url, headers=headers)
    assert response.status_code == 200 and response.json() == {'documents': []}
    assert storage.get_file_bytes_bounded.call_args.args == (
        'common/bocc_review/2026-09/manifest.json', 10_000_000,
    )
    assert (await client.get('/api/v1/admin/syncs/bocc/review?year=2026&week=0',
                             headers=headers)).status_code == 422


def test_archive_reader_handles_gzip_and_http_decoded_tar():
    import gzip
    import io
    import tarfile
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name in ['boc_2026_0000_0001.pdf', 'boc_2026_0001_p000.pdf']:
            data = b'%PDF-1.4 individual source'
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo('boc_2026_0000_link.pdf')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc/passwd'
        archive.addfile(link)
    raw_tar = stream.getvalue()
    service = BoccService()
    expected = [('boc_2026_0000_0001.pdf', b'%PDF-1.4 individual source')]
    assert service._extract_individual_pdfs(raw_tar) == expected
    assert service._extract_individual_pdfs(gzip.compress(raw_tar)) == expected
    response = httpx.Response(200, content=gzip.compress(raw_tar),
                              headers={'Content-Encoding': 'gzip'})
    assert response.content == raw_tar
    assert service._extract_individual_pdfs(response.content) == expected
    assert service._extract_individual_pdfs(b'<html>unavailable</html>') == []
