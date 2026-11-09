"""The documented team default must preserve explicit organisation roles."""

import uuid

import pytest
from sqlalchemy import select

from app.models.account_member import AccountMember
from app.models.membership import Membership
from app.models.organisation import Organisation
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


async def team(client, owner, role, access_all):
    async with session_factory() as db:
        user = (await db.scalars(select(User).where(User.email == owner["email"]))).one()
        user.owned_account.plan = "groupe"
        await db.commit()
    organisations = []
    for index in range(2):
        response = await client.post(
            "/api/v1/organisations/",
            headers=auth_header(owner["token"]),
            json={"name": f"Organisation {index}"},
        )
        assert response.status_code == 201, response.text
        organisations.append(response.json()["id"])
    invitation = await client.post(
        "/api/v1/team/invite",
        headers=auth_header(owner["token"]),
        json={
            "email": "role-member@test.com",
            "role_in_org": role,
            "access_all": access_all,
            "organisation_ids": [organisations[0]],
        },
    )
    assert invitation.status_code == 201, invitation.text
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "role-member@test.com",
            "full_name": "Member",
            "password": "SecurePass123!",
            "invited": True,
            "invitation_token": invitation.json()["token"],
        },
    )
    member_headers = auth_header(registration.json()["access_token"])
    accepted = await client.post(
        f"/api/v1/invitations/{invitation.json()['token']}/accept", headers=member_headers
    )
    assert accepted.status_code == 200, accepted.text
    rows = await client.get("/api/v1/team/members", headers=auth_header(owner["token"]))
    member = next(row for row in rows.json() if row["user_email"] == "role-member@test.com")
    return organisations, member, member_headers


@pytest.mark.parametrize("access_all", [False, True])
@pytest.mark.parametrize("old_role,new_role", [("manager", "user"), ("user", "manager")])
async def test_team_default_change_preserves_existing_roles_and_applies_to_new_orgs(
    client, manager_user, access_all, old_role, new_role
):
    organisations, member, headers = await team(client, manager_user, old_role, access_all)
    update = await client.patch(
        f"/api/v1/team/members/{member['id']}",
        headers=auth_header(manager_user["token"]),
        json={
            "role_in_org": new_role,
            "access_all": access_all,
            "organisation_ids": [organisations[0]],
        },
    )
    assert update.status_code == 200, update.text
    assert update.json()["role_in_org"] == new_role
    targets = organisations if access_all else organisations[:1]
    async with session_factory() as db:
        grants = (
            await db.scalars(
                select(Membership).where(Membership.user_id == uuid.UUID(member["user_id"]))
            )
        ).all()
        assert {str(grant.organisation_id): grant.role_in_org for grant in grants} == {
            org_id: old_role for org_id in targets
        }
    for org_id in targets:
        result = await client.patch(
            f"/api/v1/organisations/{org_id}", headers=headers, json={"name": "Updated"}
        )
        assert result.status_code == (200 if old_role == "manager" else 403), result.text
        if old_role == "user":
            deletion = await client.delete(f"/api/v1/organisations/{org_id}", headers=headers)
            assert deletion.status_code == 403
        # Ordinary conversation access is unaffected by the default role.
        conversation = await client.post(
            "/api/v1/conversations/", headers=headers, json={"organisation_id": org_id}
        )
        assert conversation.status_code == 201, conversation.text
    if not access_all:
        forbidden = await client.patch(
            f"/api/v1/organisations/{organisations[1]}", headers=headers, json={"name": "Denied"}
        )
        assert forbidden.status_code == 403
    else:
        created = await client.post(
            "/api/v1/organisations/",
            headers=auth_header(manager_user["token"]),
            json={"name": "New organisation"},
        )
        assert created.status_code == 201, created.text
        result = await client.patch(
            f"/api/v1/organisations/{created.json()['id']}",
            headers=headers,
            json={"name": "New default applied"},
        )
        assert result.status_code == (200 if new_role == "manager" else 403), result.text


async def test_team_default_change_preserves_roles_in_other_accounts(
    client, manager_user, regular_user
):
    _, member, headers = await team(client, manager_user, "manager", True)
    async with session_factory() as db:
        other_owner = (
            await db.scalars(select(User).where(User.email == regular_user["email"]))
        ).one()
        other_org = Organisation(name="Other account", account_id=other_owner.owned_account.id)
        db.add(other_org)
        await db.flush()
        db.add(
            Membership(
                user_id=uuid.UUID(member["user_id"]),
                organisation_id=other_org.id,
                role_in_org="manager",
            )
        )
        await db.commit()
        other_id = other_org.id
    update = await client.patch(
        f"/api/v1/team/members/{member['id']}",
        headers=auth_header(manager_user["token"]),
        json={"role_in_org": "user"},
    )
    assert update.status_code == 200, update.text
    response = await client.patch(
        f"/api/v1/organisations/{other_id}", headers=headers, json={"name": "Still allowed"}
    )
    assert response.status_code == 200, response.text
    async with session_factory() as db:
        grant = await db.get(AccountMember, uuid.UUID(member["id"]))
        assert grant.role_in_org == "user"


async def test_explicit_organisation_demotion_removes_manager_permissions(client, manager_user):
    organisations, member, headers = await team(client, manager_user, "manager", True)
    memberships = await client.get(
        f"/api/v1/organisations/{organisations[0]}/members",
        headers=auth_header(manager_user["token"]),
    )
    grant = next(row for row in memberships.json() if row["user_id"] == member["user_id"])
    result = await client.patch(
        f"/api/v1/organisations/{organisations[0]}/members/{grant['id']}",
        headers=auth_header(manager_user["token"]),
        json={"role_in_org": "user"},
    )
    assert result.status_code == 200, result.text
    result = await client.delete(f"/api/v1/organisations/{organisations[0]}", headers=headers)
    assert result.status_code == 403
    result = await client.patch(
        f"/api/v1/organisations/{organisations[1]}",
        headers=headers,
        json={"name": "Other explicit role preserved"},
    )
    assert result.status_code == 200, result.text
