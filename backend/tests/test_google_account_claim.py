"""A verified Google email claim must replace every pre-claim credential/session."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.auth_session import AuthSession
from app.models.conversation import Message
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


@pytest.fixture
def google_claims(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "verified-test-client")
    return {
        "iss": "https://accounts.google.com",
        "aud": "verified-test-client",
        "email": "claimed@test.com",
        "email_verified": True,
        "name": "Email owner",
        "sub": "verified-email-owner",
    }


async def google(client, claims):
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
        return await client.post("/api/v1/auth/google", json={"id_token": "x" * 200})


async def preregister(client):
    result = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "claimed@test.com",
            "full_name": "Pre-registration",
            "password": "AttackerChosenPass123!",
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


async def test_google_claim_revokes_attacker_sessions_refresh_and_password(client, google_claims):
    attacker = await preregister(client)
    second = await client.post(
        "/api/v1/auth/login",
        json={"email": "claimed@test.com", "password": "AttackerChosenPass123!"},
    )
    assert second.status_code == 200
    victim = await google(client, google_claims)
    assert victim.status_code == 200, victim.text
    victim_headers = auth_header(victim.json()["access_token"])
    organisation = await client.post(
        "/api/v1/organisations/", headers=victim_headers, json={"name": "Owner's private data"}
    )
    assert organisation.status_code == 201, organisation.text
    conversation = await client.post(
        "/api/v1/conversations/",
        headers=victim_headers,
        json={"organisation_id": organisation.json()["id"]},
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    async with session_factory() as db:
        db.add(
            Message(
                conversation_id=uuid.UUID(conversation_id), role="user", content="Private content"
            )
        )
        user = (await db.scalars(select(User).where(User.email == "claimed@test.com"))).one()
        assert user.auth_provider == "google"
        assert user.hashed_password is None
        await db.commit()
    for session in (attacker, second.json()):
        read = await client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=auth_header(session["access_token"]),
        )
        assert read.status_code == 401
        refresh = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
        )
        assert refresh.status_code == 401
    password_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "claimed@test.com", "password": "AttackerChosenPass123!"},
    )
    assert password_login.status_code == 401
    # Replaying the old refresh families must not revoke the new Google session.
    assert (
        await client.get(f"/api/v1/conversations/{conversation_id}", headers=victim_headers)
    ).status_code == 200


async def test_later_google_signins_preserve_other_legitimate_google_sessions(
    client, google_claims
):
    first = await google(client, google_claims)
    second = await google(client, google_claims)
    assert first.status_code == second.status_code == 200
    for result in (first, second):
        response = await client.get(
            "/api/v1/users/me", headers=auth_header(result.json()["access_token"])
        )
        assert response.status_code == 200
    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
    )
    assert rotated.status_code == 200


@pytest.mark.parametrize("provider", ["credentials", "google"])
async def test_legacy_linked_google_accounts_cannot_use_retained_password(
    client, google_claims, provider
):
    attacker = await preregister(client)
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == "claimed@test.com"))).one()
        user.google_sub = google_claims["sub"]
        user.auth_provider = provider
        await db.commit()
    password_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "claimed@test.com", "password": "AttackerChosenPass123!"},
    )
    assert password_login.status_code == 401
    response = await google(client, google_claims)
    assert response.status_code == 200, response.text
    old = await client.get("/api/v1/users/me", headers=auth_header(attacker["access_token"]))
    assert old.status_code == 401


@pytest.mark.parametrize("invalid", [{"email_verified": False}, {"iss": "https://invalid.test"}])
async def test_invalid_google_claim_never_changes_existing_credentials(
    client, google_claims, invalid
):
    account = await preregister(client)
    rejected = await google(client, {**google_claims, **invalid})
    assert rejected.status_code == 401
    existing = await client.get("/api/v1/users/me", headers=auth_header(account["access_token"]))
    assert existing.status_code == 200
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == "claimed@test.com"))).one()
        assert user.auth_provider == "credentials"
        assert user.google_sub is None
        assert user.hashed_password is not None


async def test_conflicting_google_identity_cannot_replace_existing_link(client, google_claims):
    first = await google(client, google_claims)
    conflicting = await google(client, {**google_claims, "sub": "another-google-identity"})
    assert conflicting.status_code == 409
    assert (
        await client.get("/api/v1/users/me", headers=auth_header(first.json()["access_token"]))
    ).status_code == 200


async def test_google_claim_during_signup_blocks_late_password_session(
    client, google_claims, monkeypatch
):
    verified = {}

    async def sign_in_during_notification(**kwargs):
        response = await google(client, google_claims)
        assert response.status_code == 200, response.text
        verified.update(response.json())

    monkeypatch.setattr(
        "app.services.auth_service._notify_admin_new_signup", sign_in_during_notification
    )
    signup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "claimed@test.com",
            "full_name": "Pre-registration",
            "password": "AttackerChosenPass123!",
        },
    )
    assert signup.status_code == 409, signup.text
    assert (
        await client.get("/api/v1/users/me", headers=auth_header(verified["access_token"]))
    ).status_code == 200
    async with session_factory() as db:
        sessions = (await db.scalars(select(AuthSession))).all()
        assert len(sessions) == 1
        assert not sessions[0].revoked
