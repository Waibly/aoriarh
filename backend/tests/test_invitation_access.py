"""Invitation access and shared account seats through both invitation routes."""

import uuid

import pytest
from sqlalchemy import select

from app.models.account import Account
from app.models.account_member import AccountMember
from app.models.membership import Membership
from app.models.user import User
from app.services.billing_service import BillingService
from app.services.plan_service import PlanOverflowError, assign_plan
from tests.conftest import auth_header, test_session_factory


async def _set_plan(email, plan):
    async with test_session_factory() as session:
        account = (
            await session.execute(
                select(Account).join(User, Account.owner_id == User.id).where(User.email == email)
            )
        ).scalar_one()
        account.plan = plan
        account.status = "active"
        account.plan_expires_at = None
        await session.commit()
        return account.id


async def _create_org(client, headers, name):
    response = await client.post("/api/v1/organisations/", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _invitation_route(scope, org_id):
    if scope == "team":
        return "/api/v1/team/invite"
    return f"/api/v1/organisations/{org_id}/invitations"


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["team", "organisation"])
async def test_solo_second_user_can_join_and_third_requires_addon(
    client, manager_user, regular_user, second_user, scope
):
    await _set_plan(manager_user["email"], "solo")
    owner = auth_header(manager_user["token"])
    invited = auth_header(regular_user["token"])
    org_id = await _create_org(client, owner, "Solo")
    route = _invitation_route(scope, org_id)

    usage = await client.get("/api/v1/billing/usage-summary", headers=owner)
    assert usage.status_code == 200
    assert usage.json()["users"] == {"used": 1, "limit": 2}

    # Both invitations can be pending while the second seat is still free.
    invitations = []
    for user in [regular_user, second_user]:
        response = await client.post(route, json={"email": user["email"]}, headers=owner)
        assert response.status_code == 201, response.text
        invitations.append(response.json())

    accepted = await client.post(
        f"/api/v1/invitations/{invitations[0]['token']}/accept", headers=invited
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    # The invitee already owns a personal trial account; it must not hide the org.
    orgs = await client.get("/api/v1/organisations/", headers=invited)
    assert orgs.status_code == 200
    assert {org["id"] for org in orgs.json()} == {org_id}
    detail = await client.get(f"/api/v1/organisations/{org_id}", headers=invited)
    assert detail.status_code == 200
    profile = await client.get(f"/api/v1/users/me?organisation_id={org_id}", headers=invited)
    assert profile.status_code == 200
    assert profile.json()["plan"] == "solo"

    usage = await client.get("/api/v1/billing/usage-summary", headers=owner)
    assert usage.json()["users"] == {"used": 2, "limit": 2}
    assert usage.json()["questions"]["limit"] == 300

    # Recheck at acceptance as well as at invitation creation, through both routes.
    blocked = await client.post(
        f"/api/v1/invitations/{invitations[1]['token']}/accept",
        headers=auth_header(second_user["token"]),
    )
    assert blocked.status_code == 403
    assert "2 utilisateurs maximum" in blocked.json()["detail"]
    for other_scope in ["team", "organisation"]:
        blocked = await client.post(
            _invitation_route(other_scope, org_id),
            json={"email": "third@test.com"},
            headers=owner,
        )
        assert blocked.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["team", "organisation"])
async def test_invitation_only_lists_authorised_organisations(
    client, manager_user, regular_user, scope
):
    await _set_plan(manager_user["email"], "invite")
    owner = auth_header(manager_user["token"])
    invited = auth_header(regular_user["token"])
    allowed_org = await _create_org(client, owner, "Allowed")
    private_org = await _create_org(client, owner, "Private")
    response = await client.post(
        _invitation_route(scope, allowed_org),
        json={
            "email": regular_user["email"],
            "access_all": False,
            "organisation_ids": [allowed_org],
        },
        headers=owner,
    )
    assert response.status_code == 201, response.text
    accepted = await client.post(
        f"/api/v1/invitations/{response.json()['token']}/accept", headers=invited
    )
    assert accepted.status_code == 200, accepted.text

    orgs = await client.get("/api/v1/organisations/", headers=invited)
    assert {org["id"] for org in orgs.json()} == {allowed_org}
    denied = await client.get(f"/api/v1/organisations/{private_org}", headers=invited)
    assert denied.status_code == 403
    owner_orgs = await client.get("/api/v1/organisations/", headers=owner)
    assert len(owner_orgs.json()) == 2
    assert {org["id"] for org in owner_orgs.json()} == {allowed_org, private_org}


@pytest.mark.asyncio
async def test_account_seats_deduplicate_team_and_direct_memberships(
    client, manager_user, regular_user
):
    account_id = await _set_plan(manager_user["email"], "invite")
    owner = auth_header(manager_user["token"])
    org_ids = [await _create_org(client, owner, name) for name in ["First", "Second"]]
    async with test_session_factory() as session:
        member_id = (
            await session.execute(select(User.id).where(User.email == regular_user["email"]))
        ).scalar_one()
        session.add(AccountMember(account_id=account_id, user_id=member_id))
        for org_id in org_ids:
            session.add(Membership(user_id=member_id, organisation_id=uuid.UUID(org_id)))
        await session.commit()
        assert await BillingService(session).count_users_on_account(account_id) == 2
    usage = await client.get("/api/v1/billing/usage-summary", headers=owner)
    assert usage.json()["users"] == {"used": 2, "limit": 5}


@pytest.mark.asyncio
async def test_plan_downgrade_counts_existing_direct_org_members(
    client, manager_user, regular_user, second_user
):
    account_id = await _set_plan(manager_user["email"], "invite")
    owner = auth_header(manager_user["token"])
    org_id = uuid.UUID(await _create_org(client, owner, "Existing direct memberships"))
    async with test_session_factory() as session:
        for user in [regular_user, second_user]:
            member_id = (
                await session.execute(select(User.id).where(User.email == user["email"]))
            ).scalar_one()
            session.add(Membership(user_id=member_id, organisation_id=org_id))
        await session.commit()
        with pytest.raises(PlanOverflowError) as error:
            await assign_plan(session, account_id, "gratuit")
        assert any("utilisateurs actifs : 3" in reason for reason in error.value.reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["team", "organisation"])
async def test_existing_org_member_can_receive_more_access_when_seats_are_full(
    client, manager_user, regular_user, second_user, scope
):
    await _set_plan(manager_user["email"], "invite")
    owner = auth_header(manager_user["token"])
    invited = auth_header(regular_user["token"])
    first_org = await _create_org(client, owner, "First access")
    second_org = await _create_org(client, owner, "Additional access")

    async with test_session_factory() as session:
        for user in [regular_user, second_user]:
            user_id = (
                await session.execute(select(User.id).where(User.email == user["email"]))
            ).scalar_one()
            session.add(Membership(user_id=user_id, organisation_id=uuid.UUID(first_org)))
        for index in range(2):
            user = User(email=f"other-{index}@test.com", full_name="Other member")
            session.add(user)
            await session.flush()
            session.add(Membership(user_id=user.id, organisation_id=uuid.UUID(first_org)))
        await session.commit()

    usage = await client.get("/api/v1/billing/usage-summary", headers=owner)
    assert usage.json()["users"] == {"used": 5, "limit": 5}
    route = _invitation_route(scope, second_org)
    response = await client.post(route, json={"email": regular_user["email"]}, headers=owner)
    assert response.status_code == 201, response.text
    accepted = await client.post(
        f"/api/v1/invitations/{response.json()['token']}/accept", headers=invited
    )
    assert accepted.status_code == 200, accepted.text
    orgs = await client.get("/api/v1/organisations/", headers=invited)
    assert {org["id"] for org in orgs.json()} == {first_org, second_org}
    usage = await client.get("/api/v1/billing/usage-summary", headers=owner)
    assert usage.json()["users"] == {"used": 5, "limit": 5}
    blocked = await client.post(route, json={"email": "new-user@test.com"}, headers=owner)
    assert blocked.status_code == 403
