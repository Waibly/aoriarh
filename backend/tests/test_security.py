"""Tests for security: password complexity, JWT token validation, multi-tenant isolation."""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, create_refresh_token, decode_access_token
from tests.conftest import auth_header


# ---- Password Complexity ----


@pytest.mark.asyncio
async def test_register_password_too_short(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "a@test.com", "password": "Short1!", "full_name": "Test"},
    )
    assert res.status_code == 422
    assert "12 caractères" in res.json()["detail"][0]["msg"]


@pytest.mark.asyncio
async def test_register_password_no_uppercase(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "b@test.com", "password": "lowercaseonly1!", "full_name": "Test"},
    )
    assert res.status_code == 422
    assert "majuscule" in res.json()["detail"][0]["msg"]


@pytest.mark.asyncio
async def test_register_password_no_digit(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "c@test.com", "password": "NoDigitsHere!!", "full_name": "Test"},
    )
    assert res.status_code == 422
    assert "chiffre" in res.json()["detail"][0]["msg"]


@pytest.mark.asyncio
async def test_register_password_no_special(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "d@test.com", "password": "NoSpecialChar1A", "full_name": "Test"},
    )
    assert res.status_code == 422
    assert "spécial" in res.json()["detail"][0]["msg"]


@pytest.mark.asyncio
async def test_register_valid_password(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "valid@test.com", "password": "ValidPass123!", "full_name": "Test"},
    )
    assert res.status_code == 201


# ---- JWT Token Type Validation ----


@pytest.mark.asyncio
async def test_refresh_token_rejected_as_access(client: AsyncClient) -> None:
    """A refresh token must NOT be accepted as an access token."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "jwt@test.com", "password": "SecurePass123!", "full_name": "JWT User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "jwt@test.com", "password": "SecurePass123!"},
    )
    refresh_token = login_res.json()["refresh_token"]

    # Try using refresh token to access a protected endpoint
    res = await client.get("/api/v1/users/me", headers=auth_header(refresh_token))
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_access_token_rejected_as_refresh(client: AsyncClient) -> None:
    """An access token must NOT be accepted as a refresh token."""
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "jwt2@test.com", "password": "SecurePass123!", "full_name": "JWT User 2"},
    )
    access_token = res.json()["access_token"]

    res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert res.status_code == 401


# ---- Multi-Tenant Isolation ----


@pytest.mark.asyncio
async def test_user_cannot_access_other_org_documents(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    """A user must not see documents from an organisation they don't belong to."""
    # Manager creates an organisation
    org_res = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Org Privée"},
    )
    org_id = org_res.json()["id"]

    # Regular user (not a member) tries to list documents
    res = await client.get(
        f"/api/v1/documents/{org_id}/",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_access_other_org_conversations(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    """A user must not create conversations in an organisation they don't belong to."""
    org_res = await client.post(
        "/api/v1/organisations/",
        headers=auth_header(manager_user["token"]),
        json={"name": "Org Privée 2"},
    )
    org_id = org_res.json()["id"]

    res = await client.post(
        "/api/v1/conversations/",
        headers=auth_header(regular_user["token"]),
        json={"organisation_id": org_id, "title": "Tentative intrusion"},
    )
    assert res.status_code == 403


# ---- Admin Endpoint Protection ----


@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin_stats(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/stats",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_list_all_documents(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    res = await client.get(
        "/api/v1/admin/documents/all",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_api(client: AsyncClient) -> None:
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401
