from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import settings
from app.models.user import User
from app.services.document_service import _safe_storage_filename, _validate_file_bytes
from tests.conftest import auth_header, test_session_factory


@pytest.mark.asyncio
async def test_google_auth_rejects_legacy_client_asserted_identity(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/google",
        json={
            "email": "victim@example.com",
            "full_name": "Victim",
            "google_sub": "attacker-controlled",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_google_auth_accepts_only_verified_server_side_claims(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "google_client_id", "expected-client-id")
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "expected-client-id",
        "sub": "google-user-123",
        "email": "verified@example.com",
        "email_verified": True,
        "name": "Verified User",
    }
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "x" * 200},
        )

    assert response.status_code == 200
    me = await client.get(
        "/api/v1/users/me",
        headers=auth_header(response.json()["access_token"]),
    )
    assert me.status_code == 200
    assert me.json()["email"] == "verified@example.com"


@pytest.mark.asyncio
async def test_refresh_token_is_single_use_and_reuse_revokes_family(client: AsyncClient) -> None:
    signup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "rotate@example.com",
            "password": "SecurePass123!",
            "full_name": "Rotate User",
        },
    )
    original = signup.json()["refresh_token"]
    rotated = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original},
    )
    assert rotated.status_code == 200
    replacement = rotated.json()["refresh_token"]

    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": original},
    )
    assert reused.status_code == 401
    family_revoked = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": replacement},
    )
    assert family_revoked.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_access_token(client: AsyncClient) -> None:
    signup = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout@example.com",
            "password": "SecurePass123!",
            "full_name": "Logout User",
        },
    )
    data = signup.json()
    response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": data["refresh_token"]},
    )
    assert response.status_code == 204
    me = await client.get(
        "/api/v1/users/me",
        headers=auth_header(data["access_token"]),
    )
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_business_admin_cannot_call_technical_admin_api(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    async with test_session_factory() as session:
        await session.execute(
            update(User)
            .where(User.email == admin_user["email"])
            .values(staff_role="business")
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/quality/metrics",
        headers=auth_header(admin_user["token"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tech_admin_cannot_call_business_admin_api(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    async with test_session_factory() as session:
        await session.execute(
            update(User)
            .where(User.email == admin_user["email"])
            .values(staff_role="tech")
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/business/overview",
        headers=auth_header(admin_user["token"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_support_email_escapes_user_controlled_html(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    send_mock = AsyncMock(return_value=True)
    with patch("app.api.support.send_email", send_mock):
        response = await client.post(
            "/api/v1/support/",
            headers=auth_header(manager_user["token"]),
            json={
                "type": "bug",
                "message": '<img src="https://attacker.invalid/pixel">',
                "page_url": '<script>alert("x")</script>',
                "user_agent": "browser",
            },
        )

    assert response.status_code == 200
    html_content = send_mock.await_args.kwargs["html_content"]
    assert "<img" not in html_content
    assert "&lt;img" in html_content
    assert "<script>" not in html_content


def test_upload_validation_rejects_spoofed_binary_and_sanitizes_name() -> None:
    with pytest.raises(Exception):
        _validate_file_bytes(b"not a pdf", "pdf")
    with pytest.raises(Exception):
        _validate_file_bytes(b"PK-not-a-real-docx", "docx")
    with pytest.raises(Exception):
        _validate_file_bytes(b"hello\x00world", "txt")

    safe = _safe_storage_filename("../../évil report?.pdf", "pdf")
    assert "/" not in safe
    assert ".." not in safe
