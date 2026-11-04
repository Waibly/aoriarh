"""Exercise the security data migration against existing sessions and grants."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.auth_session import AuthSession
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from app.services.auth_session_service import create_auth_session
from tests.conftest import auth_header
from tests.conftest import test_engine as engine
from tests.conftest import test_session_factory as session_factory


async def upgrade():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/m2security01_revoke_legacy_google_access_and_sync_team_roles.py"
    )
    spec = importlib.util.spec_from_file_location("security_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def apply(connection):
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    async with engine.begin() as connection:
        await connection.run_sync(apply)


@pytest.mark.parametrize("legacy_provider", ["google", "credentials"])
async def test_security_migration_repairs_existing_access_without_touching_other_users(
    client, legacy_provider
):
    async with session_factory() as db:
        legacy = User(
            id=uuid.uuid4(),
            email="legacy@test.com",
            full_name="Legacy",
            hashed_password="legacy-password-hash",
            auth_provider=legacy_provider,
            google_sub="legacy-google-id",
        )
        clean = User(
            id=uuid.uuid4(),
            email="clean@test.com",
            full_name="Clean Google",
            auth_provider="google",
            google_sub="clean-google-id",
        )
        credentials = User(
            id=uuid.uuid4(),
            email="password@test.com",
            full_name="Password owner",
            hashed_password="unchanged-password-hash",
            auth_provider="credentials",
        )
        promoted = User(id=uuid.uuid4(), email="promoted@test.com", full_name="Promoted")
        db.add_all([legacy, clean, credentials, promoted])
        await db.flush()
        account = Account(id=uuid.uuid4(), name="Team", owner_id=credentials.id)
        other = Account(id=uuid.uuid4(), name="Other", owner_id=clean.id)
        db.add_all([account, other])
        await db.flush()
        organisation = Organisation(id=uuid.uuid4(), name="Team org", account_id=account.id)
        outside = Organisation(id=uuid.uuid4(), name="Outside", account_id=other.id)
        db.add_all([organisation, outside])
        await db.flush()
        db.add_all(
            [
                AccountMember(account_id=account.id, user_id=legacy.id, role_in_org="user"),
                AccountMember(account_id=account.id, user_id=promoted.id, role_in_org="manager"),
                Membership(
                    user_id=legacy.id, organisation_id=organisation.id, role_in_org="manager"
                ),
                Membership(
                    user_id=promoted.id, organisation_id=organisation.id, role_in_org="user"
                ),
                Membership(
                    user_id=credentials.id, organisation_id=organisation.id, role_in_org="manager"
                ),
                Membership(user_id=legacy.id, organisation_id=outside.id, role_in_org="manager"),
            ]
        )
        sessions = {}
        for user in (legacy, clean, credentials):
            access, _ = await create_auth_session(db, user.id)
            sessions[user.id] = access
        await db.commit()

    assert (
        await client.get("/api/v1/users/me", headers=auth_header(sessions[legacy.id]))
    ).status_code == 200
    await upgrade()
    async with session_factory() as db:
        repaired = await db.get(User, legacy.id)
        assert repaired.auth_provider == "google"
        assert repaired.hashed_password is None
        assert (await db.get(User, credentials.id)).hashed_password == "unchanged-password-hash"
        assert (await db.get(User, clean.id)).hashed_password is None
        active = (await db.scalars(select(AuthSession).where(AuthSession.revoked.is_(False)))).all()
        assert {session.user_id for session in active} == {clean.id, credentials.id}
        grants = (await db.scalars(select(Membership))).all()
        roles = {(grant.user_id, grant.organisation_id): grant.role_in_org for grant in grants}
        assert roles == {
            (legacy.id, organisation.id): "user",
            (promoted.id, organisation.id): "manager",
            (credentials.id, organisation.id): "manager",
            (legacy.id, outside.id): "manager",
        }
        fresh_google, _ = await create_auth_session(db, legacy.id)
        await db.commit()
    for user in (clean, credentials):
        assert (
            await client.get("/api/v1/users/me", headers=auth_header(sessions[user.id]))
        ).status_code == 200
    assert (
        await client.get("/api/v1/users/me", headers=auth_header(sessions[legacy.id]))
    ).status_code == 401
    # Applying the data fix again must leave the new legitimate session intact.
    await upgrade()
    assert (
        await client.get("/api/v1/users/me", headers=auth_header(fresh_google))
    ).status_code == 200
