"""Concurrent refreshes of one session must not log the user out.

Incident 2026-11-04: Next.js middleware and /api/auth/session refreshed the same
expired session 12 ms apart; the second call was taken for token theft and the
whole session family was revoked.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from starlette.requests import Request

from app.core.limiter import INTERNAL_KEY, per_visitor, rate_limit_key
from app.models.auth_session import AuthSession
from tests.conftest import auth_header, test_session_factory


async def _signup(client: AsyncClient, email: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass123!", "full_name": "Grace User"},
    )
    assert response.status_code == 201
    return response.json()


async def _refresh(client: AsyncClient, token: str):
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def _age_rotations(seconds: int) -> None:
    async with test_session_factory() as db:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.last_used_at.is_not(None))
            .values(last_used_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_refresh_keeps_both_results_valid(client: AsyncClient) -> None:
    original = (await _signup(client, "concurrent@example.com"))["refresh_token"]

    first = await _refresh(client, original)
    second = await _refresh(client, original)

    assert first.status_code == 200
    assert second.status_code == 200
    for result in (first, second):
        tokens = result.json()
        me = await client.get("/api/v1/users/me", headers=auth_header(tokens["access_token"]))
        assert me.status_code == 200
        # Each branch keeps rotating normally afterwards.
        assert (await _refresh(client, tokens["refresh_token"])).status_code == 200


@pytest.mark.asyncio
async def test_reuse_after_grace_window_still_revokes_family(client: AsyncClient) -> None:
    original = (await _signup(client, "late-reuse@example.com"))["refresh_token"]
    replacement = (await _refresh(client, original)).json()

    await _age_rotations(seconds=120)

    assert (await _refresh(client, original)).status_code == 401
    assert (await _refresh(client, replacement["refresh_token"])).status_code == 401
    me = await client.get("/api/v1/users/me", headers=auth_header(replacement["access_token"]))
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_grace_window_cannot_resurrect_logged_out_session(client: AsyncClient) -> None:
    original = (await _signup(client, "logged-out@example.com"))["refresh_token"]
    replacement = (await _refresh(client, original)).json()["refresh_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": replacement})
    assert logout.status_code == 204

    assert (await _refresh(client, original)).status_code == 401


@pytest.mark.asyncio
async def test_never_rotated_revoked_token_is_rejected(client: AsyncClient) -> None:
    token = (await _signup(client, "revoked@example.com"))["refresh_token"]
    await client.post("/api/v1/auth/logout", json={"refresh_token": token})

    assert (await _refresh(client, token)).status_code == 401


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_rate_limit_key_uses_real_visitor_ip_behind_proxy() -> None:
    # Caddy (private Docker IP) forwarding two different visitors.
    assert rate_limit_key(_request("172.18.0.13", "203.0.113.7")) == "203.0.113.7"
    assert rate_limit_key(_request("172.18.0.13", "198.51.100.9")) == "198.51.100.9"
    # A spoofed header from a public peer is ignored.
    assert rate_limit_key(_request("8.8.8.8", "1.2.3.4")) == "8.8.8.8"
    # Our own Next.js server without visitor IP gets the internal budget.
    assert rate_limit_key(_request("172.18.0.16")) == INTERNAL_KEY


def test_per_visitor_gives_internal_calls_a_wider_budget() -> None:
    provider = per_visitor("10/minute")
    assert provider("203.0.113.7") == "10/minute"
    assert provider(INTERNAL_KEY) == "600/minute"
