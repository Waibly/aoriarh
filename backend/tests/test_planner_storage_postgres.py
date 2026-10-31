"""Opt-in, disposable PostgreSQL 16 test. Never connects to application stores.

Run with AORIA_LOCAL_POSTGRES_TESTS=1. Requires Docker and a cached postgres:16-alpine
image; the container has a random localhost-only port and an in-memory data directory.
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.base import Base
from app.models.case_file import CaseEntry, CaseEvent, CaseFile, CaseTask
from app.models.conversation import Message
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.services.conversation_service import ConversationService
from scripts.audit_answers import parse_sse
from tests.test_chat_stream_timeouts import _passthrough_intent
from tests.test_conversation_orchestrator import planner
from tests.test_conversation_requests import fact, request, wire


@pytest.fixture(scope="module")
def postgres_url():
    if os.environ.get("AORIA_LOCAL_POSTGRES_TESTS") != "1":
        pytest.skip("Explicit local Docker/PostgreSQL opt-in only")
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail("Docker is required by the explicitly enabled PostgreSQL test")
    name = f"aoriarh-test-planner-storage-{uuid.uuid4().hex}"
    try:
        subprocess.run(
            [
                docker,
                "run",
                "--detach",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--label",
                "aoriarh.test=planner-storage",
                "--publish",
                "127.0.0.1::5432",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--env",
                "POSTGRES_USER=storage_test",
                "--env",
                "POSTGRES_PASSWORD=test-only",
                "--env",
                "POSTGRES_DB=storage_test",
                "postgres:16-alpine",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=30,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [
                    docker,
                    "exec",
                    name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "storage_test",
                    "-d",
                    "storage_test",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            pytest.fail("Disposable PostgreSQL did not become ready")
        port = subprocess.check_output([docker, "port", name, "5432/tcp"], text=True)
        assert port.startswith("127.0.0.1:")
        yield URL.create(
            "postgresql+asyncpg",
            username="storage_test",
            password="test-only",
            host="127.0.0.1",
            port=int(port.strip().rsplit(":", 1)[1]),
            database="storage_test",
        )
    finally:
        subprocess.run(
            [docker, "rm", "--force", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )


@pytest.fixture
async def postgres_factory(postgres_url):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_postgres_rejects_decoded_nul_but_accepts_literal_backslash_text(postgres_factory):
    async with postgres_factory() as db:
        with pytest.raises(DBAPIError) as failure:
            await db.scalar(
                text("SELECT CAST(:payload AS jsonb)"),
                {
                    "payload": json.dumps({"text": "salari\x00e9"}),
                },
            )
        assert failure.value.orig.sqlstate == "22P05"
        await db.rollback()
        literal = r"Texte original \u0000"
        stored = await db.scalar(
            text("SELECT CAST(:payload AS jsonb)"),
            {
                "payload": json.dumps({"text": literal}),
            },
        )
        assert stored == {"text": literal}


async def test_http_preserves_raw_and_exposes_error_without_partial_dossier_changes(
    postgres_factory,
    monkeypatch,
):
    async with postgres_factory() as db:
        actor = User(email="storage@example.test", full_name="Storage test")
        outsider = User(email="outsider@example.test", full_name="Other test")
        org = Organisation(name="Isolated storage test")
        db.add_all([actor, outsider, org])
        await db.flush()
        db.add(Membership(user_id=actor.id, organisation_id=org.id, role_in_org="user"))
        await db.commit()
        conv = await ConversationService(db).create_conversation(org.id, actor, "Storage")
        conv_id = conv.id
        case = await db.scalar(select(CaseFile).where(CaseFile.conversation_id == conv_id))
        case_id, initial_version = case.id, case.version
        initial_entries = await db.scalar(
            select(func.count()).select_from(CaseEntry).where(CaseEntry.case_file_id == case_id)
        )

    async def local_db():
        async with postgres_factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, local_db)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: actor)
    monkeypatch.setattr("app.api.conversations.classify_intent", _passthrough_intent)
    monkeypatch.setattr(
        "app.api.conversations.BillingService",
        lambda db: SimpleNamespace(
            get_account_for_organisation=AsyncMock(return_value=SimpleNamespace()),
            check_question_quota=AsyncMock(),
            increment_question_count=AsyncMock(),
            ensure_plan_active=MagicMock(),
        ),
    )
    raw = (
        "  " + wire([request(question="Texte salari\x00e9"), request(id="other")], [fact()]) + "\n"
    )
    agent = planner(raw)
    agent.stream_generate = MagicMock(side_effect=AssertionError("No generation for invalid plan"))
    legal = AsyncMock(side_effect=AssertionError("No search for invalid plan"))
    monkeypatch.setattr("app.api.conversations.RAGAgent", lambda: agent)
    monkeypatch.setattr("app.api.conversations.prepare_rag_context", legal)
    url = f"/api/v1/conversations/{conv_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(url + "/chat/stream", json={"message": "Rédige un mail"})
        assert response.status_code == 200, response.text
        error = next(
            item["data"] for item in parse_sse(response.text) if item["event"] == "chat_error"
        )
        assert error["error"] == "search_planner_error"
        assert error["technical_error"] == "planner_json_contains_nul"
        assert "chat_done" not in response.text
        events = await client.get(url + "/case-file/events")
        assert events.status_code == 200, events.text
        event = next(
            item for item in events.json()["items"] if item["type"] == "planner_observation"
        )
        assert event["raw_planner_output"] == raw
        assert event["structured_delta"] is None
        assert event["technical_error"] == "planner_json_contains_nul"
        assert events.headers["cache-control"] == "private, no-store"
        monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: outsider)
        assert (await client.get(url + "/case-file/events")).status_code in {403, 404}
    agent.llm.chat.completions.create.assert_awaited_once()
    agent.stream_generate.assert_not_called()
    legal.assert_not_awaited()
    async with postgres_factory() as db:
        assert await db.scalar(select(CaseFile.version).where(CaseFile.id == case_id)) == (
            initial_version
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(CaseEntry).where(CaseEntry.case_file_id == case_id)
            )
            == initial_entries
        )
        assert (
            await db.scalar(
                select(func.count()).select_from(CaseTask).where(CaseTask.case_file_id == case_id)
            )
            == 0
        )
        messages = list(await db.scalars(select(Message).where(Message.conversation_id == conv_id)))
        assert [(msg.role, msg.content) for msg in messages] == [("user", "Rédige un mail")]
        stored = await db.scalar(select(CaseEvent).where(CaseEvent.id == uuid.UUID(event["id"])))
        assert stored.raw_planner_output.encode() == raw.encode()
