"""Tests de la persistance de l'attribution marketing à l'inscription.

Parcours couvert : le site vitrine capture utm_*/gclid/msclkid à la première
visite, l'app les transmet à POST /auth/register (ou, pour le parcours OAuth,
via POST /users/me/attribution après connexion), et notre base devient
l'arbitre de mesure via GET /admin/business/signups-by-source.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.user import User
from tests.conftest import auth_header, test_session_factory

ATTRIBUTION = {
    "utm_source": "google",
    "utm_medium": "cpc",
    "utm_campaign": "test",
    "utm_term": "logiciel rh",
    "utm_content": "annonce-a",
    "gclid": "TEST123",
    "msclkid": None,
    "referrer": "https://www.google.com/",
    "landing_page": "https://aoriarh.fr/?utm_source=google&utm_campaign=test&gclid=TEST123",
}


async def _get_user(email: str) -> User:
    async with test_session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one()


@pytest.mark.asyncio
async def test_register_persists_attribution(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "attr@example.com",
            "password": "SecurePass123!",
            "full_name": "Attr User",
            "attribution": ATTRIBUTION,
        },
    )
    assert response.status_code == 201

    user = await _get_user("attr@example.com")
    assert user.utm_source == "google"
    assert user.utm_medium == "cpc"
    assert user.utm_campaign == "test"
    assert user.utm_term == "logiciel rh"
    assert user.utm_content == "annonce-a"
    assert user.gclid == "TEST123"
    assert user.msclkid is None
    assert user.referrer == "https://www.google.com/"
    assert user.landing_page.startswith("https://aoriarh.fr/")
    assert user.attributed_at is not None


@pytest.mark.asyncio
async def test_register_without_attribution(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "direct@example.com",
            "password": "SecurePass123!",
            "full_name": "Direct User",
        },
    )
    assert response.status_code == 201

    user = await _get_user("direct@example.com")
    assert user.utm_source is None
    assert user.gclid is None
    assert user.attributed_at is None


@pytest.mark.asyncio
async def test_register_truncates_overlong_values(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "long@example.com",
            "password": "SecurePass123!",
            "full_name": "Long User",
            "attribution": {
                "utm_source": "x" * 500,
                "landing_page": "https://aoriarh.fr/?" + "y" * 2000,
            },
        },
    )
    assert response.status_code == 201

    user = await _get_user("long@example.com")
    assert len(user.utm_source) == 255
    assert len(user.landing_page) == 1024


@pytest.mark.asyncio
async def test_attribution_endpoint_sets_when_absent(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "oauth@example.com",
            "password": "SecurePass123!",
            "full_name": "OAuth User",
        },
    )
    token = res.json()["access_token"]

    response = await client.post(
        "/api/v1/users/me/attribution",
        json=ATTRIBUTION,
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["detail"] == "enregistrée"

    user = await _get_user("oauth@example.com")
    assert user.utm_source == "google"
    assert user.gclid == "TEST123"
    assert user.attributed_at is not None


@pytest.mark.asyncio
async def test_attribution_endpoint_keeps_first_touch(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "first@example.com",
            "password": "SecurePass123!",
            "full_name": "First Touch",
            "attribution": ATTRIBUTION,
        },
    )
    token = res.json()["access_token"]

    response = await client.post(
        "/api/v1/users/me/attribution",
        json={"utm_source": "bing", "utm_campaign": "autre", "msclkid": "MS999"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["detail"] == "ignorée"

    user = await _get_user("first@example.com")
    assert user.utm_source == "google"
    assert user.utm_campaign == "test"
    assert user.msclkid is None


@pytest.mark.asyncio
async def test_attribution_endpoint_ignores_empty_payload(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "empty@example.com",
            "password": "SecurePass123!",
            "full_name": "Empty Attr",
        },
    )
    token = res.json()["access_token"]

    response = await client.post(
        "/api/v1/users/me/attribution",
        json={},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["detail"] == "ignorée"

    user = await _get_user("empty@example.com")
    assert user.attributed_at is None


@pytest.mark.asyncio
async def test_signups_by_source_aggregates(
    client: AsyncClient, admin_user: dict[str, str]
) -> None:
    for i in range(2):
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"ads{i}@example.com",
                "password": "SecurePass123!",
                "full_name": f"Ads User {i}",
                "attribution": ATTRIBUTION,
            },
        )
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "organic@example.com",
            "password": "SecurePass123!",
            "full_name": "Organic User",
            "attribution": {"utm_source": "linkedin", "utm_medium": "social"},
        },
    )
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "noattr@example.com",
            "password": "SecurePass123!",
            "full_name": "No Attr",
        },
    )

    response = await client.get(
        "/api/v1/admin/business/signups-by-source",
        headers=auth_header(admin_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()

    # admin_user + 4 inscriptions du test
    assert data["total_signups"] == 5
    assert data["attributed_signups"] == 3

    by_source = {(r["utm_source"], r["utm_campaign"]): r for r in data["rows"]}
    google_row = by_source[("google", "test")]
    assert google_row["signups"] == 2
    assert google_row["with_gclid"] == 2
    assert google_row["utm_medium"] == "cpc"
    linkedin_row = by_source[("linkedin", None)]
    assert linkedin_row["signups"] == 1
    assert linkedin_row["with_gclid"] == 0


@pytest.mark.asyncio
async def test_signups_by_source_requires_admin(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/admin/business/signups-by-source",
        headers=auth_header(regular_user["token"]),
    )
    assert response.status_code == 403
