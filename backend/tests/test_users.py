import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.get("/api/v1/users/me", headers=auth_header(regular_user["token"]))
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "user@test.com"
    assert data["full_name"] == "Regular User"


@pytest.mark.asyncio
async def test_update_name(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.patch(
        "/api/v1/users/me",
        headers=auth_header(regular_user["token"]),
        json={"full_name": "Nouveau Nom"},
    )
    assert res.status_code == 200
    assert res.json()["full_name"] == "Nouveau Nom"


@pytest.mark.asyncio
async def test_update_email_conflict(
    client: AsyncClient, regular_user: dict[str, str], second_user: dict[str, str]
):
    res = await client.patch(
        "/api/v1/users/me",
        headers=auth_header(regular_user["token"]),
        json={"email": "user2@test.com"},
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_change_password_ok(client: AsyncClient, regular_user: dict[str, str]):
    res = await client.post(
        "/api/v1/users/me/password",
        headers=auth_header(regular_user["token"]),
        json={"current_password": "SecurePass123!", "new_password": "NewPass456!xyz"},
    )
    assert res.status_code == 200
    assert res.json()["detail"] == "Mot de passe modifié"


@pytest.mark.asyncio
async def test_change_password_wrong_current(
    client: AsyncClient, regular_user: dict[str, str]
):
    res = await client.post(
        "/api/v1/users/me/password",
        headers=auth_header(regular_user["token"]),
        json={"current_password": "wrongpass", "new_password": "newpass456"},
    )
    assert res.status_code == 400
