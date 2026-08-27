import uuid
from unittest.mock import Mock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.fiche import Fiche
from app.models.organisation import Organisation
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory

# --- Organisation CRUD ---


@pytest.mark.asyncio
async def test_create_organisation_as_manager(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/organisations/",
        json={"name": "Test Corp", "forme_juridique": "SAS", "taille": "11-19"},
        headers=auth_header(manager_user["token"]),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Corp"
    assert data["forme_juridique"] == "SAS"
    assert data["taille"] == "11-19"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_organisation_as_regular_user_forbidden(
    client: AsyncClient, regular_user: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/organisations/",
        json={"name": "Forbidden Corp"},
        headers=auth_header(regular_user["token"]),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_organisation_auto_adds_creator_as_manager(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "My Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    members_res = await client.get(
        f"/api/v1/organisations/{org_id}/members",
        headers=auth_header(manager_user["token"]),
    )
    assert members_res.status_code == 200
    members = members_res.json()
    assert len(members) == 1
    assert members[0]["role_in_org"] == "manager"
    assert members[0]["user_email"] == "manager@test.com"


@pytest.mark.asyncio
async def test_list_organisations_only_shows_own(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/organisations/",
        json={"name": "Manager Org"},
        headers=auth_header(manager_user["token"]),
    )
    res = await client.get(
        "/api/v1/organisations/",
        headers=auth_header(regular_user["token"]),
    )
    assert res.status_code == 200
    assert len(res.json()) == 0


@pytest.mark.asyncio
async def test_get_organisation_non_member_forbidden(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Private Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    res2 = await client.get(
        f"/api/v1/organisations/{org_id}",
        headers=auth_header(regular_user["token"]),
    )
    assert res2.status_code == 403


@pytest.mark.asyncio
async def test_update_organisation_as_manager(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Old Name"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    res2 = await client.patch(
        f"/api/v1/organisations/{org_id}",
        json={"name": "New Name"},
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 200
    assert res2.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_organisation_also_deletes_its_fiches(
    client: AsyncClient,
    manager_user: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qdrant = Mock()
    monkeypatch.setattr(
        "app.services.organisation_service.get_qdrant_client",
        lambda: qdrant,
    )
    response = await client.post(
        "/api/v1/organisations/",
        json={"name": "Organisation avec fiche"},
        headers=auth_header(manager_user["token"]),
    )
    organisation_id = response.json()["id"]

    async with session_factory() as session:
        user_id = (
            await session.execute(
                select(User.id).where(User.email == manager_user["email"])
            )
        ).scalar_one()
        fiche = Fiche(
            organisation_id=uuid.UUID(organisation_id),
            user_id=user_id,
            title="Fiche empêchant la suppression",
            content={},
            sources=[],
        )
        session.add(fiche)
        await session.commit()
        fiche_id = fiche.id

    delete_response = await client.delete(
        f"/api/v1/organisations/{organisation_id}",
        headers=auth_header(manager_user["token"]),
    )

    assert delete_response.status_code == 204
    qdrant.delete.assert_called_once()
    async with session_factory() as session:
        assert await session.get(Fiche, fiche_id) is None
        assert await session.get(Organisation, uuid.UUID(organisation_id)) is None


# --- Member management ---


@pytest.mark.asyncio
async def test_invite_member(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Invite Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    res2 = await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com", "role_in_org": "user"},
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 201
    assert res2.json()["user_email"] == "user@test.com"
    assert res2.json()["role_in_org"] == "user"


@pytest.mark.asyncio
async def test_invite_duplicate_member(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Dup Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com"},
        headers=auth_header(manager_user["token"]),
    )
    res2 = await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com"},
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 409


@pytest.mark.asyncio
async def test_change_member_role(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Role Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    invite_res = await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com"},
        headers=auth_header(manager_user["token"]),
    )
    membership_id = invite_res.json()["id"]

    res2 = await client.patch(
        f"/api/v1/organisations/{org_id}/members/{membership_id}",
        json={"role_in_org": "manager"},
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 200
    assert res2.json()["role_in_org"] == "manager"


@pytest.mark.asyncio
async def test_remove_member(
    client: AsyncClient, manager_user: dict[str, str], regular_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Remove Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    invite_res = await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com"},
        headers=auth_header(manager_user["token"]),
    )
    membership_id = invite_res.json()["id"]

    res2 = await client.delete(
        f"/api/v1/organisations/{org_id}/members/{membership_id}",
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 204


@pytest.mark.asyncio
async def test_cannot_remove_last_manager(
    client: AsyncClient, manager_user: dict[str, str]
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "Last Manager Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]

    members_res = await client.get(
        f"/api/v1/organisations/{org_id}/members",
        headers=auth_header(manager_user["token"]),
    )
    manager_membership_id = members_res.json()[0]["id"]

    res2 = await client.delete(
        f"/api/v1/organisations/{org_id}/members/{manager_membership_id}",
        headers=auth_header(manager_user["token"]),
    )
    assert res2.status_code == 400


# --- Multi-tenant isolation ---


@pytest.mark.asyncio
async def test_non_member_cannot_see_members(
    client: AsyncClient,
    manager_user: dict[str, str],
    regular_user: dict[str, str],
    second_user: dict[str, str],
) -> None:
    res_a = await client.post(
        "/api/v1/organisations/",
        json={"name": "Org A"},
        headers=auth_header(manager_user["token"]),
    )
    org_a_id = res_a.json()["id"]
    await client.post(
        f"/api/v1/organisations/{org_a_id}/members",
        json={"email": "user@test.com"},
        headers=auth_header(manager_user["token"]),
    )

    res_members = await client.get(
        f"/api/v1/organisations/{org_a_id}/members",
        headers=auth_header(regular_user["token"]),
    )
    assert res_members.status_code == 200

    res_forbidden = await client.get(
        f"/api/v1/organisations/{org_a_id}/members",
        headers=auth_header(second_user["token"]),
    )
    assert res_forbidden.status_code == 403


@pytest.mark.asyncio
async def test_regular_user_cannot_invite_members(
    client: AsyncClient,
    manager_user: dict[str, str],
    regular_user: dict[str, str],
    second_user: dict[str, str],
) -> None:
    res = await client.post(
        "/api/v1/organisations/",
        json={"name": "No Invite Org"},
        headers=auth_header(manager_user["token"]),
    )
    org_id = res.json()["id"]
    await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user@test.com", "role_in_org": "user"},
        headers=auth_header(manager_user["token"]),
    )

    res2 = await client.post(
        f"/api/v1/organisations/{org_id}/members",
        json={"email": "user2@test.com"},
        headers=auth_header(regular_user["token"]),
    )
    assert res2.status_code == 403
