"""Real invitation/authentication flow; no Stripe request may escape the owner guard."""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.models.account_member import AccountMember
from app.models.user import User
from tests.conftest import auth_header
from tests.conftest import test_session_factory as session_factory


@pytest.mark.parametrize("role", ["user", "manager"])
async def test_invited_member_cannot_manage_billing(client, manager_user, monkeypatch, role):
    async with session_factory() as db:
        owner = (await db.scalars(select(User).where(User.email == manager_user["email"]))).one()
        owner.owned_account.plan = "equipe"
        await db.commit()
    invitation = await client.post(
        "/api/v1/team/invite",
        headers=auth_header(manager_user["token"]),
        json={"email": "invited-billing@test.com", "role_in_org": role},
    )
    assert invitation.status_code == 201, invitation.text
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "invited-billing@test.com",
            "password": "SecurePass123!",
            "full_name": "Invited member",
            "invited": True,
            "invitation_token": invitation.json()["token"],
        },
    )
    headers = auth_header(registered.json()["access_token"])
    accepted = await client.post(
        f"/api/v1/invitations/{invitation.json()['token']}/accept", headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    service = Mock(side_effect=AssertionError("Stripe must not be reached"))
    invoices = Mock(side_effect=AssertionError("Stripe must not be reached"))
    monkeypatch.setattr("app.api.billing.StripeService", service)
    monkeypatch.setattr("app.api.billing.stripe.Invoice.list", invoices)
    for method, path, payload in [
        ("POST", "/checkout", {"plan": "solo", "cycle": "monthly"}),
        ("POST", "/booster/checkout", None),
        ("POST", "/change-plan", {"plan": "solo", "cycle": "monthly"}),
        ("POST", "/preview-change-plan", {"plan": "solo", "cycle": "monthly"}),
        ("POST", "/cancel", None),
        ("POST", "/reactivate", None),
        ("POST", "/addons", {"addon_type": "extra_user"}),
        ("DELETE", f"/addons/{uuid.uuid4()}", None),
        ("POST", "/portal", None),
        ("POST", "/payment-method/update", None),
        ("GET", "/invoices", None),
    ]:
        response = await client.request(
            method, f"/api/v1/billing{path}", headers=headers, json=payload
        )
        assert response.status_code == 403, (method, path, response.text)
    service.assert_not_called()
    invoices.assert_not_called()
    quota = await client.get("/api/v1/billing/quota", headers=headers)
    assert quota.status_code == 200
    assert quota.json()["plan"] == "equipe"
    # Existing limit dialogs also need these read-only views.
    for path in ("/subscription", "/addons", "/usage-summary"):
        response = await client.get(f"/api/v1/billing{path}", headers=headers)
        assert response.status_code == 200, response.text


async def test_owner_only_manages_their_own_account(
    client, manager_user, regular_user, monkeypatch
):
    async with session_factory() as db:
        owner = (await db.scalars(select(User).where(User.email == manager_user["email"]))).one()
        member = (await db.scalars(select(User).where(User.email == regular_user["email"]))).one()
        own_account_id = member.owned_account.id
        db.add(AccountMember(account_id=owner.owned_account.id, user_id=member.id))
        await db.commit()
    cancel = AsyncMock(return_value={"plan": "solo"})
    monkeypatch.setattr(
        "app.services.stripe_service.StripeService.cancel_subscription_at_period_end", cancel
    )
    response = await client.post(
        "/api/v1/billing/cancel", headers=auth_header(regular_user["token"])
    )
    assert response.status_code == 200, response.text
    assert cancel.await_args.args[0].id == own_account_id
