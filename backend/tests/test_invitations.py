"""Tests for the invitation system."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, test_session_factory


# --- Helpers ---

async def create_org(client: AsyncClient, token: str) -> str:
    """Create an org and return its id."""
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Test Corp", "forme_juridique": "SAS", "taille": "11-50"},
        headers=auth_header(token),
    )
    assert res.status_code == 201
    return res.json()["id"]


async def create_invitation(
    client: AsyncClient, org_id: str, token: str, email: str = "invited@test.com"
) -> dict:
    """Create an invitation and return its data."""
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": email, "role_in_org": "user"},
        headers=auth_header(token),
    )
    assert res.status_code == 201
    return res.json()


# --- Access control ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_only_manager_can_create_invitation(
    mock_send, client: AsyncClient, manager_user, regular_user
):
    org_id = await create_org(client, manager_user["token"])
    # regular user is NOT a member → should fail
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": "someone@test.com", "role_in_org": "user"},
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_only_manager_can_list_invitations(
    mock_send, client: AsyncClient, manager_user, regular_user
):
    org_id = await create_org(client, manager_user["token"])
    res = await client.get(
        f"/api/v1/organisations/{org_id}/invitations",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_unauthenticated_cannot_create_invitation(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": "someone@test.com", "role_in_org": "user"},
    )
    assert res.status_code == 401


# --- Create invitation ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_create_invitation_success(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": "invited@test.com", "role_in_org": "user"},
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "invited@test.com"
    assert data["status"] == "pending"
    assert data["role_in_org"] == "user"
    assert "token" in data
    mock_send.assert_called_once()


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_create_invitation_duplicate_pending_409(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])
    await create_invitation(client, org_id, manager_user["token"])
    # Try again with same email
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": "invited@test.com", "role_in_org": "user"},
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 409


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_create_invitation_already_member_409(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])
    # Manager is already a member of the org
    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations",
        json={"email": manager_user["email"], "role_in_org": "user"},
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 409


# --- List invitations ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_list_invitations(mock_send, client: AsyncClient, manager_user):
    org_id = await create_org(client, manager_user["token"])
    await create_invitation(client, org_id, manager_user["token"], "a@test.com")
    await create_invitation(client, org_id, manager_user["token"], "b@test.com")

    res = await client.get(
        f"/api/v1/organisations/{org_id}/invitations",
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2


# --- Cancel invitation ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_cancel_invitation(mock_send, client: AsyncClient, manager_user):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"])

    res = await client.delete(
        f"/api/v1/organisations/{org_id}/invitations/{inv['id']}",
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 204

    # Verify it's cancelled
    res = await client.get(
        f"/api/v1/organisations/{org_id}/invitations",
        headers=auth_header(manager_user["token"]),
    )
    cancelled = [i for i in res.json() if i["id"] == inv["id"]]
    assert cancelled[0]["status"] == "cancelled"


# --- Resend invitation ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_resend_invitation(mock_send, client: AsyncClient, manager_user):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"])
    original_token = inv["token"]

    res = await client.post(
        f"/api/v1/organisations/{org_id}/invitations/{inv['id']}/resend",
        headers=auth_header(manager_user["token"]),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["token"] != original_token
    assert mock_send.call_count == 2  # once for create, once for resend


# --- Validate token ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_validate_token_valid(mock_send, client: AsyncClient, manager_user):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"])

    res = await client.get(f"/api/v1/invitations/{inv['token']}/validate")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["email"] == "invited@test.com"
    assert data["organisation_name"] == "Test Corp"


@pytest.mark.asyncio
async def test_validate_token_invalid(client: AsyncClient):
    fake_token = str(uuid.uuid4())
    res = await client.get(f"/api/v1/invitations/{fake_token}/validate")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_validate_token_expired(mock_send, client: AsyncClient, manager_user):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"])

    # Manually expire the invitation
    from app.models.invitation import Invitation
    from sqlalchemy import update

    async with test_session_factory() as session:
        await session.execute(
            update(Invitation)
            .where(Invitation.id == uuid.UUID(inv["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()

    res = await client.get(f"/api/v1/invitations/{inv['token']}/validate")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert data["status"] == "expired"


# --- Accept invitation ---


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_accept_invitation_success(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])

    # Register a new user for the invitation
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "invited@test.com",
            "password": "SecurePass123!",
            "full_name": "Invited User",
        },
    )
    invited_token = reg_res.json()["access_token"]

    inv = await create_invitation(client, org_id, manager_user["token"])

    res = await client.post(
        f"/api/v1/invitations/{inv['token']}/accept",
        headers=auth_header(invited_token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "accepted"
    assert data["organisation_id"] == org_id


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_accept_invitation_wrong_email_403(
    mock_send, client: AsyncClient, manager_user, regular_user
):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"], "other@test.com")

    res = await client.post(
        f"/api/v1/invitations/{inv['token']}/accept",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_accept_invitation_expired_410(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])

    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "invited@test.com",
            "password": "SecurePass123!",
            "full_name": "Invited User",
        },
    )
    invited_token = reg_res.json()["access_token"]

    inv = await create_invitation(client, org_id, manager_user["token"])

    # Manually expire
    from app.models.invitation import Invitation
    from sqlalchemy import update

    async with test_session_factory() as session:
        await session.execute(
            update(Invitation)
            .where(Invitation.id == uuid.UUID(inv["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()

    res = await client.post(
        f"/api/v1/invitations/{inv['token']}/accept",
        headers=auth_header(invited_token),
    )
    assert res.status_code == 410


@pytest.mark.asyncio
@patch("app.services.invitation_service.send_email", new_callable=AsyncMock)
async def test_accept_invitation_unauthenticated(
    mock_send, client: AsyncClient, manager_user
):
    org_id = await create_org(client, manager_user["token"])
    inv = await create_invitation(client, org_id, manager_user["token"])

    res = await client.post(f"/api/v1/invitations/{inv['token']}/accept")
    assert res.status_code == 401
