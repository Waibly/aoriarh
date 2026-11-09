import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.base import Base
from app.models.invitation import Invitation
from app.models.plan_invitation import PlanInvitation, PlanInvitationRedemption
from app.models.user import User
from app.services.plan_invitation_service import PlanInvitationService
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def promo(client, admin_user, **overrides):
    response = await client.post(
        "/api/v1/admin/plan-invitations",
        headers=auth_header(admin_user["token"]),
        json={"label": "Test invitation", "duration_months": 3, "max_uses": 1, **overrides},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_single_use_link_recognises_beneficiary_after_exhaustion(
    client, admin_user, manager_user
):
    link = await promo(client, admin_user)
    path = f"/api/v1/plan-invitations/{link['token']}/redeem"
    first = await client.post(path, headers=auth_header(manager_user["token"]))
    again = await client.post(path, headers=auth_header(manager_user["token"]))
    assert first.status_code == again.status_code == 200
    assert first.json()["status"] == "redeemed"
    assert again.json()["status"] == "already_redeemed"
    # SQLite drops timezone metadata when loading the committed row.
    assert datetime.fromisoformat(first.json()["plan_expires_at"]).replace(tzinfo=UTC) == (
        datetime.fromisoformat(again.json()["plan_expires_at"]).replace(tzinfo=UTC)
    )
    async with session_factory() as db:
        link = await db.get(PlanInvitation, uuid.UUID(link["id"]))
        assert link.use_count == 1
        assert link.status == "exhausted"
        assert await db.scalar(select(func.count()).select_from(PlanInvitationRedemption)) == 1


async def test_notification_failure_does_not_split_activation(
    client, admin_user, manager_user, monkeypatch
):
    link = await promo(client, admin_user)
    monkeypatch.setattr("app.services.email.sender.send_email", AsyncMock(side_effect=TimeoutError))
    response = await client.post(
        f"/api/v1/plan-invitations/{link['token']}/redeem",
        headers=auth_header(manager_user["token"]),
    )
    assert response.status_code == 200, response.text
    async with session_factory() as db:
        invitation = await db.get(PlanInvitation, uuid.UUID(link["id"]))
        user = await db.scalar(select(User).where(User.email == manager_user["email"]))
        assert user.owned_account.plan == "invite"
        assert invitation.use_count == 1
        assert await db.scalar(select(func.count()).select_from(PlanInvitationRedemption)) == 1


async def test_plan_failure_rolls_back_reserved_use(client, admin_user, manager_user, monkeypatch):
    link = await promo(client, admin_user)
    monkeypatch.setattr(
        "app.services.plan_invitation_service.assign_plan", AsyncMock(side_effect=RuntimeError)
    )
    with pytest.raises(RuntimeError):
        await client.post(
            f"/api/v1/plan-invitations/{link['token']}/redeem",
            headers=auth_header(manager_user["token"]),
        )
    async with session_factory() as db:
        invitation = await db.get(PlanInvitation, uuid.UUID(link["id"]))
        assert invitation.use_count == 0
        assert invitation.status == "active"
        assert await db.scalar(select(func.count()).select_from(PlanInvitationRedemption)) == 0


async def test_last_use_cannot_be_consumed_by_two_accounts(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'invitation.sqlite'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            users = [
                User(email=f"race-{i}@test.com", full_name="Race", role="manager") for i in range(2)
            ]
            db.add_all(users)
            await db.flush()
            for user in users:
                db.add(Account(owner_id=user.id, name="Race", plan="gratuit", status="active"))
            await db.commit()
            ids = [user.id for user in users]
            invitation = await PlanInvitationService(db).create(
                label="Last use",
                plan="invite",
                duration_months=3,
                created_by=ids[0],
                max_uses=1,
            )
            token = invitation.token

        async def redeem(user_id):
            async with factory() as db:
                user = await db.get(User, user_id)
                try:
                    return (await PlanInvitationService(db).redeem(token, user))["status"]
                except HTTPException as error:
                    return error.status_code

        results = await asyncio.gather(*(redeem(user_id) for user_id in ids))
        assert results.count("redeemed") == 1
        assert results.count(410) == 1
        async with factory() as db:
            invitation = await db.scalar(select(PlanInvitation))
            assert invitation.use_count == 1
            assert await db.scalar(select(func.count()).select_from(PlanInvitationRedemption)) == 1
            assert (
                await db.scalar(
                    select(func.count()).select_from(Account).where(Account.plan == "invite")
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("wrong_token", [False, True])
async def test_invited_registration_requires_matching_invitation(client, wrong_token):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "orphan@test.com",
            "full_name": "Orphan",
            "password": "SecurePass123!",
            "invited": True,
            "invitation_token": str(uuid.uuid4()) if wrong_token else None,
        },
    )
    assert response.status_code == 400
    async with session_factory() as db:
        assert await db.scalar(select(User).where(User.email == "orphan@test.com")) is None


async def test_legacy_unattached_user_recovers_at_login(client):
    async with session_factory() as db:
        db.add(
            User(
                email="legacy@test.com",
                full_name="Legacy",
                role="user",
                hashed_password=hash_password("SecurePass123!"),
            )
        )
        await db.commit()
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "legacy@test.com",
            "password": "SecurePass123!",
        },
    )
    assert response.status_code == 200
    me = await client.get("/api/v1/users/me", headers=auth_header(response.json()["access_token"]))
    assert me.json()["role"] == "manager"
    assert me.json()["workspace_id"]
    assert me.json()["can_create_organisation"] is True


async def test_unverified_legacy_identity_cannot_retrieve_an_invitation_token(client, manager_user):
    async with session_factory() as db:
        owner = await db.scalar(select(User).where(User.email == manager_user["email"]))
        db.add(
            User(
                email="legacy-invited@test.com",
                full_name="Legacy",
                role="user",
                hashed_password=hash_password("SecurePass123!"),
            )
        )
        db.add(
            Invitation(
                email="legacy-invited@test.com",
                account_id=owner.owned_account.id,
                invited_by=owner.id,
                role_in_org="user",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await db.commit()
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "legacy-invited@test.com",
            "password": "SecurePass123!",
        },
    )
    assert login.status_code == 200
    me = await client.get("/api/v1/users/me", headers=auth_header(login.json()["access_token"]))
    assert me.json()["pending_invitation_token"] is None


@pytest.mark.parametrize("expired", [False, True])
async def test_google_handles_multiple_and_expired_invitations(
    client, manager_user, monkeypatch, expired
):
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_oauth2_token",
        lambda *args, **kwargs: {
            "iss": "accounts.google.com",
            "email_verified": True,
            "email": "google-invited@test.com",
            "sub": "google-invited",
            "name": "Invited",
        },
    )
    async with session_factory() as db:
        owner = await db.scalar(select(User).where(User.email == manager_user["email"]))
        for _ in range(2):
            db.add(
                Invitation(
                    email="google-invited@test.com",
                    account_id=owner.owned_account.id,
                    invited_by=owner.id,
                    role_in_org="user",
                    expires_at=datetime.now(UTC) + timedelta(days=-1 if expired else 1),
                )
            )
        await db.commit()
    response = await client.post("/api/v1/auth/google", json={"id_token": "x" * 100})
    assert response.status_code == 200, response.text
    me = await client.get("/api/v1/users/me", headers=auth_header(response.json()["access_token"]))
    assert me.json()["role"] == ("manager" if expired else "user")
    assert bool(me.json()["pending_invitation_token"]) is not expired


async def test_creation_rights_are_scoped_to_selected_workspace(client, manager_user, second_user):
    async with session_factory() as db:
        a = await db.scalar(select(User).where(User.email == manager_user["email"]))
        b = await db.scalar(select(User).where(User.email == second_user["email"]))
        invitation = Invitation(
            email="scoped@test.com",
            account_id=a.owned_account.id,
            invited_by=a.id,
            role_in_org="user",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(invitation)
        await db.commit()
        token, aid, bid = invitation.token, a.owned_account.id, b.owned_account.id
    signup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "scoped@test.com",
            "full_name": "Scoped",
            "password": "SecurePass123!",
            "invited": True,
            "invitation_token": str(token),
        },
    )
    headers = auth_header(signup.json()["access_token"])
    async with session_factory() as db:
        user = await db.scalar(select(User).where(User.email == "scoped@test.com"))
        db.add(AccountMember(user_id=user.id, account_id=aid, role_in_org="user"))
        db.add(AccountMember(user_id=user.id, account_id=bid, role_in_org="manager"))
        await db.commit()
    profile = await client.get("/api/v1/users/me", headers=headers)
    assert profile.json()["can_create_organisation"] is False
    default_target = await client.post(
        "/api/v1/organisations/", headers=headers, json={"name": "No explicit target"}
    )
    assert default_target.status_code == 403
    denied = await client.post(
        "/api/v1/organisations/",
        headers=headers,
        json={
            "name": "Forbidden",
            "account_id": str(aid),
        },
    )
    assert denied.status_code == 403
    allowed = await client.post(
        "/api/v1/organisations/",
        headers=headers,
        json={
            "name": "Allowed",
            "account_id": str(bid),
            "not_subject_to_ccn": True,
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["account_id"] == str(bid)
    assert allowed.json()["not_subject_to_ccn"] is True
    me = await client.get(
        f"/api/v1/users/me?organisation_id={allowed.json()['id']}", headers=headers
    )
    assert me.json()["can_create_organisation"] is True


async def test_rejected_invitation_email_does_not_create_pending_record(
    client, manager_user, monkeypatch
):
    async with session_factory() as db:
        owner = await db.scalar(select(User).where(User.email == manager_user["email"]))
        owner.owned_account.plan = "invite"
        await db.commit()
    monkeypatch.setattr(
        "app.services.account_member_service.send_email", AsyncMock(return_value=False)
    )
    response = await client.post(
        "/api/v1/team/invite",
        headers=auth_header(manager_user["token"]),
        json={"email": "rejected@test.com"},
    )
    assert response.status_code == 502
    async with session_factory() as db:
        assert (
            await db.scalar(select(Invitation).where(Invitation.email == "rejected@test.com"))
            is None
        )


async def test_admin_can_read_every_page_and_filter_used_links(client, admin_user):
    async with session_factory() as db:
        owner = await db.scalar(select(User).where(User.email == admin_user["email"]))
        for i in range(21):
            db.add(
                PlanInvitation(
                    label=f"Link {i}",
                    plan="invite",
                    duration_months=1,
                    created_by=owner.id,
                    status="exhausted" if i == 0 else "active",
                    use_count=1 if i == 0 else 0,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        await db.commit()
    headers = auth_header(admin_user["token"])
    first = await client.get("/api/v1/admin/plan-invitations?page=1", headers=headers)
    second = await client.get("/api/v1/admin/plan-invitations?page=2", headers=headers)
    used = await client.get("/api/v1/admin/plan-invitations?status=exhausted", headers=headers)
    assert first.json()["total"] == 21
    assert len(first.json()["items"]) == 20
    assert len(second.json()["items"]) == len(used.json()["items"]) == 1
