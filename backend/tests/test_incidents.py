"""Technical delivery/security contracts; never evaluate LLM content."""

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api import telemetry
from app.observability import store
from app.observability.jobs import observed_job
from app.observability.middleware import IncidentMiddleware
from app.observability.notifier import deliver_one, expected_start
from app.observability.streams import observe_stream


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("INCIDENT_DB", str(tmp_path / "incidents.sqlite3"))
    telemetry._buckets.clear()
    token = store.context.set(None)
    yield
    store.context.reset(token)


def records():
    with store.connection() as db:
        return [dict(r) for r in db.execute("SELECT * FROM incidents")]


def test_privacy_and_deduplication(spool):
    token = store.context.set({"incident_key": "request:test", "request_id": str(uuid.uuid4())})
    store.capture(
        "http_error", status=500, message="secret RH", location="/demo?q=private", token="secret"
    )
    store.capture("ui_error", status=500)
    store.context.reset(token)
    rows = records()
    assert len(rows) == 1
    assert "secret" not in rows[0]["payload"] and "private" not in rows[0]["payload"]
    assert json.loads(rows[0]["payload"])["code"] == "http_error"


def test_logging_does_not_copy_message_or_exception(spool):
    record = logging.LogRecord(
        "app.example", logging.ERROR, "/private/path", 42, "RH %s", ("secret",), None
    )
    store.IncidentLogHandler().emit(record)
    assert "secret" not in records()[0]["payload"]
    assert json.loads(records()[0]["payload"])["line"] == 42


async def test_http_exception_and_response_have_request_id(spool):
    from app.main import _unhandled_exception_handler

    app = FastAPI()
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    @app.get("/handled")
    async def handled():
        raise HTTPException(422, "private payload")

    @app.get("/crash")
    async def crash():
        raise RuntimeError("private exception")

    app.add_middleware(IncidentMiddleware)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/handled")
        assert response.status_code == 422
        assert response.headers["x-request-id"]
        crash = await client.get("/crash")
        assert crash.status_code == 500
        assert crash.headers["x-request-id"]
    assert len(records()) == 2
    assert "private" not in str(records())


async def test_public_collector_rejects_secrets_and_deduplicates(spool):
    app = FastAPI()
    app.include_router(telemetry.router)
    data = {"id": str(uuid.uuid4()), "source": "app", "code": "network_error", "location": "/demo"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/incidents", json=data)).status_code == 403
        headers = {"Origin": "https://app.aoriarh.fr"}
        assert (
            await client.post("/incidents", json={**data, "message": "private"}, headers=headers)
        ).status_code == 422
        assert (
            await client.post("/incidents", content="x" * 2049, headers=headers)
        ).status_code == 413
        assert (await client.post("/incidents", json=data, headers=headers)).status_code == 202
        assert (await client.post("/incidents", json=data, headers=headers)).status_code == 202
    assert len(records()) == 1


async def test_stream_preserves_every_frame_and_reports_failure(spool):
    frames = [
        'event: chat_delta\ndata: {"content":"  original text  "}\n\n',
        'event: chat_error\ndata: {"message":"technical error"}\n\n',
    ]

    async def generator():
        for frame in frames:
            yield frame

    class Request:
        async def is_disconnected(self):
            return False

    assert [frame async for frame in observe_stream(generator(), Request())] == frames
    assert len(records()) == 1
    assert "original text" not in records()[0]["payload"]


async def test_swallowed_job_error_is_recorded_and_results_unchanged(spool):
    @observed_job
    async def run_example(ctx):
        store.capture("document_failed")
        return {"errors": 1}

    assert await run_example({"job_id": "job-1"}) == {"errors": 1}
    assert json.loads(records()[0]["payload"])["job_id"] == "job-1"


async def test_delivery_retry_and_acceptance(spool):
    store.capture("test_incident")
    with store.connection() as db:
        db.execute("UPDATE incidents SET created=?", (time.time() - 10,))
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(429, headers={"Retry-After": "60"})
            if calls == 1
            else httpx.Response(200, text="ok")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await deliver_one(client, "https://hooks.slack.com/services/test")
        row = records()[0]
        assert row["state"] == "pending" and row["attempts"] == 1
        assert row["next_attempt"] >= time.time() + 58
        store.set_state("slack_backoff", 0)
        with store.connection() as db:
            db.execute("UPDATE incidents SET next_attempt=0")
        await deliver_one(client, "https://hooks.slack.com/services/test")
        assert records()[0]["state"] == "delivered"
        assert calls == 2


async def test_permanent_delivery_error_retained_without_retry(spool):
    store.capture("test_incident")
    with store.connection() as db:
        db.execute("UPDATE incidents SET created=?", (time.time() - 10,))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(403, text="private"))
    ) as client:
        await deliver_one(client, "https://hooks.slack.com/services/test")
        assert records()[0]["state"] == "failed"
        assert records()[0]["last_error"] == "http_403"
        assert await deliver_one(client, "https://hooks.slack.com/services/test") is False


def test_schedule_uses_calendar_not_time_since_last_run():
    sunday = datetime(2026, 10, 11, 3, 0, tzinfo=UTC)
    assert expected_start(sunday, (6, 2, 0, None)) == sunday.replace(hour=2)
    assert expected_start(sunday, (5, 2, 0, None)).day == 10


async def test_admin_incidents_denies_anonymous(client, spool):
    assert (await client.get("/api/v1/telemetry/admin/incidents")).status_code == 401
    assert (
        await client.post("/api/v1/telemetry/admin/incidents/" + str(uuid.uuid4()) + "/retry")
    ).status_code == 401


async def test_retry_budget_is_bounded(spool):
    store.capture("test_incident")
    with store.connection() as db:
        db.execute("UPDATE incidents SET created=?,attempts=7", (time.time() - 10,))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        await deliver_one(client, "https://hooks.slack.com/services/test")
        assert records()[0]["state"] == "failed"
        assert records()[0]["attempts"] == 8


async def test_collector_cannot_impersonate_authenticated_user(spool):
    app = FastAPI()
    app.include_router(telemetry.router)
    data = {
        "id": str(uuid.uuid4()),
        "source": "app",
        "code": "ui_error",
        "user_id": str(uuid.uuid4()),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.post("/incidents", json=data, headers={"Origin": "https://app.aoriarh.fr"})
        ).status_code == 422
    assert records() == []


async def test_queue_tracks_only_successfully_enqueued_jobs(spool):
    from app.observability.jobs import track_queue

    class Job:
        job_id = "queued-1"

    class Pool:
        async def enqueue_job(self, name, *args, **kwargs):
            return Job()

    pool = Pool()
    track_queue(pool)
    await pool.enqueue_job("run_ingestion", "doc-1")
    assert store.get_state("job:queued-1")["status"] == "queued"


async def test_cancelled_job_remains_visible(spool):
    @observed_job
    async def run_cancelled(ctx):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_cancelled({"job_id": "cancelled-1"})
    assert store.get_state("job:cancelled-1")["status"] == "cancelled"
    assert json.loads(records()[0]["payload"])["code"] == "job_cancelled"


async def test_slack_groups_occurrences_but_keeps_individual_records(spool):
    for number in range(281):
        store.capture('http_error', source='backend', status=404,
                      location='unmatched_route', request_id=str(uuid.uuid4()))
    with store.connection() as db:
        db.execute('UPDATE incidents SET created=?', (time.time() - 10,))
    messages = []

    def handler(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200, text='ok')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        assert not await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert len(messages) == 1
    assert 'Occurrences regroupées : 281' in messages[0]['blocks'][0]['text']['text']
    assert len(records()) == 281
    assert all(row['state'] == 'delivered' and row['attempts'] == 1 for row in records())


async def test_slack_cooldown_survives_new_events_and_does_not_block_other_groups(spool):
    def add(source):
        store.capture('ui_error', source=source)
        with store.connection() as db:
            db.execute("UPDATE incidents SET created=? WHERE state='pending'", (time.time() - 10,))

    messages = []

    def handler(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200, text='ok')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        add('nextjs')
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        add('nextjs')
        assert not await deliver_one(client, 'https://hooks.slack.com/services/test')
        add('app')
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        assert sum(r['state'] == 'pending' for r in records()) == 1
        with store.connection() as db:
            db.execute("UPDATE state SET value='0' WHERE key LIKE 'slack_group:%'")
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert len(messages) == 3
    assert all(r['state'] == 'delivered' for r in records())


async def test_slack_batch_failure_preserves_each_incident_retry_budget(spool):
    store.capture('document_failed', document_id=str(uuid.uuid4()))
    store.capture('document_failed', document_id=str(uuid.uuid4()))
    with store.connection() as db:
        db.execute('UPDATE incidents SET created=?', (time.time() - 10,))
        db.execute('UPDATE incidents SET attempts=7 WHERE id=?', (records()[0]['id'],))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert sorted((r['state'], r['attempts']) for r in records()) == [('failed', 8), ('pending', 1)]


@pytest.mark.parametrize('reason,label', [
    ('provider_quota_exhausted', 'Crédits OpenAI épuisés'),
    ('provider_rate_limited', 'Limite de débit du service IA atteinte'),
    ('server_error', 'Erreur technique du service IA'),
])
async def test_server_and_browser_share_one_incident_with_cause(spool, reason, label):
    request_id = str(uuid.uuid4())
    token = store.context.set({'incident_key': 'request:' + request_id,
                               'request_id': request_id, 'source': 'backend'})
    # The server log may precede the protocol error. Its cause must still be enriched.
    store.capture('python_error', exception_type='RateLimitError')
    frame = (
        'event: chat_error\ndata: '
        + json.dumps({'error': reason, 'message': 'PRIVATE'}) + '\n\n'
    )

    async def frames():
        yield frame

    class Request:
        async def is_disconnected(self):
            return False

    assert [f async for f in observe_stream(frames(), Request())] == [frame]
    store.context.reset(token)
    app = FastAPI()
    app.include_router(telemetry.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/incidents', headers={'Origin': 'https://app.aoriarh.fr'},
                                     json={'id': str(uuid.uuid4()), 'source': 'app',
                                           'code': 'stream_error', 'reason': reason,
                                           'request_id': request_id})
        assert response.status_code == 202
    assert len(records()) == 1
    assert json.loads(records()[0]['payload'])['reason'] == reason
    assert 'PRIVATE' not in records()[0]['payload']
    with store.connection() as db:
        db.execute('UPDATE incidents SET created=?', (time.time() - 10,))
    messages = []

    def accept(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200, text='ok')

    async with AsyncClient(transport=httpx.MockTransport(accept)) as client:
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        assert not await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert len(messages) == 1
    assert label in messages[0]['text']
    assert records()[0]['state'] == 'delivered'


async def test_collector_rejects_arbitrary_reason_text(spool):
    app = FastAPI()
    app.include_router(telemetry.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/incidents', headers={'Origin': 'https://app.aoriarh.fr'},
                                     json={'id': str(uuid.uuid4()), 'source': 'app',
                                           'code': 'stream_error', 'reason': 'PRIVATE'})
    assert response.status_code == 422
    assert records() == []


async def test_distinct_causes_are_not_grouped_together(spool):
    for reason in ('provider_quota_exhausted', 'provider_rate_limited'):
        store.capture('stream_error', source='app', reason=reason)
    with store.connection() as db:
        db.execute('UPDATE incidents SET created=?', (time.time() - 10,))
    messages = []

    def accept(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200, text='ok')

    async with AsyncClient(transport=httpx.MockTransport(accept)) as client:
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert len(messages) == 2
    assert messages[0]['text'] != messages[1]['text']


@pytest.mark.parametrize('origin,source', [
    ('https://aoriarh.fr', 'site'),
    ('https://www.aoriarh.fr', 'site'),
    ('https://aoriarh.fr', 'app'),
    ('https://app.aoriarh.fr', 'site'),
])
async def test_marketing_events_are_acknowledged_without_recording(spool, origin, source):
    app = FastAPI()
    app.include_router(telemetry.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/incidents', headers={'Origin': origin}, json={
            'id': str(uuid.uuid4()), 'source': source, 'code': 'resource_error', 'location': '/',
        })
    assert response.status_code == 202
    assert response.json()['ignored'] is True
    assert records() == []


async def test_old_site_backlog_is_never_delivered_but_app_errors_are(spool):
    for state in ('pending', 'failed'):
        incident_id = store.capture('resource_error', source='site')
        with store.connection() as db:
            db.execute('UPDATE incidents SET state=? WHERE id=?', (state, incident_id))
    store.capture('stream_error', source='app', reason='provider_quota_exhausted')
    with store.connection() as db:
        db.execute('UPDATE incidents SET created=?', (time.time() - 10,))
    messages = []

    def accept(request):
        messages.append(json.loads(request.content))
        return httpx.Response(200, text='ok')

    async with AsyncClient(transport=httpx.MockTransport(accept)) as client:
        assert await deliver_one(client, 'https://hooks.slack.com/services/test')
        assert not await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert len(messages) == 1
    assert 'Crédits OpenAI épuisés' in messages[0]['text']
    assert sorted(r['state'] for r in records()) == ['delivered', 'ignored', 'ignored']


async def test_marketing_tool_api_errors_keep_site_scope(spool):
    app = FastAPI()

    @app.get('/api/v1/public/tools/test')
    async def tool():
        store.IncidentLogHandler().emit(logging.LogRecord(
            'app.public_tools', logging.ERROR, '/private', 1, 'private message', (), None,
        ))
        raise HTTPException(500, 'technical error')

    app.add_middleware(IncidentMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/api/v1/public/tools/test')).status_code == 500
    assert len(records()) == 1
    assert json.loads(records()[0]['payload'])['source'] == 'site'
    async with AsyncClient(transport=httpx.MockTransport(
        lambda _: pytest.fail('Site incident must not reach Slack')
    )) as client:
        assert not await deliver_one(client, 'https://hooks.slack.com/services/test')
    assert records()[0]['state'] == 'ignored'
