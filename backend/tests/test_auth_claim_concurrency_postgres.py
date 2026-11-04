"""Opt-in auth races on disposable loopback PostgreSQL; never use application stores.

Run with AORIA_LOCAL_POSTGRES_TESTS=1 and a cached postgres:16-alpine Docker image.
"""

import asyncio
import importlib.util
import os
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.account_member import AccountMember
from app.models.auth_session import AuthSession
from app.models.base import Base
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.services.auth_session_service import revoke_all_user_sessions


@pytest.fixture(scope="module")
def postgres_url():
    if os.environ.get("AORIA_LOCAL_POSTGRES_TESTS") != "1":
        pytest.skip("Explicit local Docker/PostgreSQL opt-in only")
    name = "aoriarh-test-auth-" + uuid.uuid4().hex
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--label",
                "aoriarh.test=auth-claims",
                "--publish",
                "127.0.0.1::5432",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--env",
                "POSTGRES_USER=auth_test",
                "--env",
                "POSTGRES_PASSWORD=test-only",
                "--env",
                "POSTGRES_DB=auth_test",
                "postgres:16-alpine",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=30,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "auth_test", "-d", "auth_test"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            pytest.fail("Disposable PostgreSQL did not become ready")
        address = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True).strip()
        assert address.startswith("127.0.0.1:")
        yield URL.create(
            "postgresql+asyncpg",
            username="auth_test",
            password="test-only",
            host="127.0.0.1",
            port=int(address.rsplit(":", 1)[1]),
            database="auth_test",
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )


@pytest.fixture
async def isolated_auth(postgres_url):
    tag = "auth_probe_" + uuid.uuid4().hex
    engine = create_async_engine(
        postgres_url,
        execution_options={"schema_translate_map": {None: tag}},
        connect_args={"server_settings": {"application_name": tag, "lock_timeout": "5s"}},
    )
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{tag}"'))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def dependency():
        async with factory() as db:
            yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = dependency
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            signup = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "claim@test.com",
                    "full_name": "Pre-registration",
                    "password": "AttackerChosenPass123!",
                },
            )
            assert signup.status_code == 201, signup.text
            async with factory() as db:
                user_id = (await db.scalars(select(User.id))).one()
            yield SimpleNamespace(
                client=client,
                factory=factory,
                engine=engine,
                tag=tag,
                user_id=user_id,
                tokens=signup.json(),
            )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{tag}" CASCADE'))
        await engine.dispose()


async def wait_for_blocked_request(env):
    async def wait():
        while True:
            async with env.engine.connect() as connection:
                blocked = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name = :tag AND wait_event_type = 'Lock'"
                    ),
                    {"tag": env.tag},
                )
            if blocked:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), 5)


@pytest.mark.parametrize("operation", ["login", "refresh"])
async def test_google_claim_cannot_be_followed_by_late_password_or_refresh_session(
    isolated_auth, operation
):
    env = isolated_auth
    pending = None
    try:
        async with env.factory() as claim:
            user = (
                await claim.scalars(select(User).where(User.id == env.user_id).with_for_update())
            ).one()
            payload = (
                {"email": "claim@test.com", "password": "AttackerChosenPass123!"}
                if operation == "login"
                else {"refresh_token": env.tokens["refresh_token"]}
            )
            pending = asyncio.create_task(
                env.client.post(f"/api/v1/auth/{operation}", json=payload)
            )
            await wait_for_blocked_request(env)
            # The real Google flow owns this same user lock before it removes
            # credentials and revokes every pre-claim session.
            user.auth_provider = "google"
            user.google_sub = "verified-owner"
            user.hashed_password = None
            await revoke_all_user_sessions(claim, user.id)
            await claim.commit()
        response = await asyncio.wait_for(pending, 10)
        assert response.status_code == 401, response.text
        async with env.factory() as db:
            active = (
                await db.scalars(select(AuthSession).where(AuthSession.revoked.is_(False)))
            ).all()
            assert active == []
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_existing_security_data_is_repaired_on_postgres(isolated_auth):
    env = isolated_auth
    async with env.factory() as db:
        user = await db.get(User, env.user_id)
        user.auth_provider = "google"
        user.google_sub = "legacy-google-id"
        member = User(email="migrated@test.com", full_name="Member")
        db.add(member)
        await db.flush()
        organisation = Organisation(name="Migration org", account_id=user.owned_account.id)
        db.add(organisation)
        await db.flush()
        db.add(
            AccountMember(account_id=user.owned_account.id, user_id=member.id, role_in_org="user")
        )
        db.add(
            Membership(user_id=member.id, organisation_id=organisation.id, role_in_org="manager")
        )
        await db.commit()
        member_id = member.id
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/m2security01_revoke_legacy_google_access_and_sync_team_roles.py"
    )
    spec = importlib.util.spec_from_file_location("pg_security_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply(connection):
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    async with env.engine.begin() as connection:
        # The migration uses unqualified SQL exactly as in production. Keep it
        # inside this disposable test schema, independently of ORM translation.
        await connection.execute(text(f'SET LOCAL search_path TO "{env.tag}", public'))
        await connection.run_sync(apply)
    async with env.factory() as db:
        assert (await db.get(User, env.user_id)).hashed_password is None
        grants = (await db.scalars(select(Membership).where(Membership.user_id == member_id))).all()
        assert [grant.role_in_org for grant in grants] == ["user"]
    result = await env.client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer " + env.tokens["access_token"]},
    )
    assert result.status_code == 401
