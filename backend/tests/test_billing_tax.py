"""Territorial routing, customer isolation and Stripe tax contracts."""

from unittest.mock import Mock

import pytest
import stripe
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.models.account import Account
from app.services.billing_tax import billing_tax_policy
from app.services.stripe_service import StripeService
from tests.conftest import auth_header, test_session_factory


def stripe_customer(country="FR", postal_code="75001", *, professional=True):
    return stripe.Customer.construct_from(
        {
            "id": "cus_tax",
            "name": "Entreprise test",
            "address": {
                "line1": "1 rue du Test",
                "line2": "",
                "city": "Ville",
                "postal_code": postal_code,
                "country": country,
            },
            "metadata": {"aoria_professional": "true" if professional else "false"},
        },
        "sk_test_fake",
    )


def stripe_list(data):
    return stripe.ListObject.construct_from(
        {"object": "list", "data": data, "has_more": False}, "sk_test_fake"
    )


@pytest.mark.parametrize(
    ("country", "postal", "territory", "mode"),
    [
        ("FR", "75001", "FR", "automatic"),
        ("FR", "97410", "RE", "dom_vat"),
        ("RE", "97410", "RE", "dom_vat"),
        ("FR", "97110", "GP", "dom_vat"),
        ("MQ", "97200", "MQ", "dom_vat"),
        ("FR", "97300", "GF", "no_tax"),
        ("YT", "97600", "YT", "no_tax"),
        ("FR", "97133", "BL", "no_tax"),
        ("PM", "97500", "PM", "no_tax"),
        ("FR", "98800", "NC", "no_tax"),
        ("WF", "98600", "WF", "no_tax"),
        ("DE", "10115", "DE", "automatic"),
    ],
)
def test_tax_territory_uses_billing_establishment(country, postal, territory, mode):
    policy = billing_tax_policy(country, postal)
    assert (policy.territory, policy.mode) == (territory, mode)
    if territory in {"GF", "YT", "NC", "BL", "PM", "WF"}:
        assert policy.invoice_mention


@pytest.mark.parametrize(
    ("country", "postal"),
    [
        ("MF", "97150"),
        ("FR", "97150"),
        ("GP", "97150"),
        ("PF", "98713"),
        ("FR", "98713"),
        ("RE", "75001"),
        ("FR", "974"),
    ],
)
def test_blocked_territory_and_inconsistent_postal_address(country, postal):
    with pytest.raises(HTTPException) as exc:
        billing_tax_policy(country, postal)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("path", ["/checkout", "/booster/checkout"])
async def test_blocked_address_cannot_start_a_payment(client, regular_user, monkeypatch, path):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_solo")
    monkeypatch.setattr(settings, "stripe_price_booster", "price_booster")
    async with test_session_factory() as db:
        account = (await db.scalars(select(Account))).one()
        account.stripe_customer_id = "cus_tax"
        await db.commit()
    monkeypatch.setattr(stripe.Subscription, "list", lambda **kw: stripe_list([]))
    monkeypatch.setattr(
        stripe.Customer, "retrieve", lambda *a, **kw: stripe_customer("FR", "98713")
    )
    create = Mock(side_effect=AssertionError("Blocked territory must never reach Checkout"))
    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    response = await client.post(
        f"/api/v1/billing{path}",
        headers=auth_header(regular_user["token"]),
        json={"plan": "solo", "cycle": "monthly"} if path == "/checkout" else None,
    )
    assert response.status_code == 422, response.text
    create.assert_not_called()


async def test_reunion_checkout_sets_recurring_and_initial_tax(client, regular_user, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_solo")
    async with test_session_factory() as db:
        account = (await db.scalars(select(Account))).one()
        account.stripe_customer_id = "cus_tax"
        await db.commit()
    monkeypatch.setattr(stripe.Subscription, "list", lambda **kw: stripe_list([]))
    monkeypatch.setattr(
        stripe.Customer, "retrieve", lambda *a, **kw: stripe_customer("RE", "97410")
    )
    monkeypatch.setattr(
        stripe.TaxRate,
        "list",
        lambda **kw: stripe_list(
            [
                {
                    "id": "txr_dom",
                    "percentage": 8.5,
                    "inclusive": False,
                    "metadata": {"aoria_tax": "dom_vat_8_5"},
                }
            ]
        ),
    )
    create = Mock(return_value={"id": "cs_tax", "url": "https://checkout.stripe.com/test"})
    monkeypatch.setattr(stripe.checkout.Session, "create", create)
    response = await client.post(
        "/api/v1/billing/checkout",
        headers=auth_header(regular_user["token"]),
        json={"plan": "solo", "cycle": "monthly"},
    )
    assert response.status_code == 200, response.text
    params = create.call_args.kwargs
    assert params["automatic_tax"] == {"enabled": False}
    assert "tax_rates" not in params["line_items"][0]
    assert params["subscription_data"]["default_tax_rates"] == ["txr_dom"]
    assert "address" not in params["customer_update"]


async def test_profile_address_change_updates_renewals_without_proration(
    client, regular_user, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    async with test_session_factory() as db:
        account = (await db.scalars(select(Account))).one()
        account.stripe_customer_id = "cus_tax"
        await db.commit()
    modify_customer = Mock(return_value=stripe_customer("RE", "97410"))
    monkeypatch.setattr(stripe.Customer, "modify", modify_customer)
    monkeypatch.setattr(
        stripe.Subscription,
        "list",
        lambda **kw: stripe_list(
            [
                {
                    "id": "sub_tax",
                    "status": "active",
                    "items": {"data": [{"id": "si_tax", "tax_rates": []}]},
                },
            ]
        ),
    )
    monkeypatch.setattr("app.services.stripe_tax_service.dom_vat_rate_id", lambda: "txr_dom")
    modify_sub = Mock()
    monkeypatch.setattr(stripe.Subscription, "modify", modify_sub)
    body = {
        "business_name": "Entreprise test",
        "line1": "1 rue du Test",
        "line2": "",
        "city": "Saint-Pierre",
        "country": "FR",
        "postal_code": "97410",
        "professional": True,
    }
    response = await client.put(
        "/api/v1/billing/profile", headers=auth_header(regular_user["token"]), json=body
    )
    assert response.status_code == 200, response.text
    assert modify_customer.call_args.args == ("cus_tax",)
    assert modify_customer.call_args.kwargs["address"]["country"] == "RE"
    params = modify_sub.call_args.kwargs
    assert params["default_tax_rates"] == ["txr_dom"]
    assert params["automatic_tax"] == {"enabled": False}
    assert params["proration_behavior"] == "none"


async def test_missing_billing_coordinates_fail_before_customer_creation(
    client, regular_user, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_solo")
    create = Mock(side_effect=AssertionError("No Stripe mutation without coordinates"))
    monkeypatch.setattr(stripe.Customer, "create", create)
    response = await client.post(
        "/api/v1/billing/checkout",
        headers=auth_header(regular_user["token"]),
        json={"plan": "solo", "cycle": "monthly"},
    )
    assert response.status_code == 409, response.text
    create.assert_not_called()


@pytest.mark.parametrize(
    ("country", "postal", "held"),
    [
        ("FR", "97150", True),
        ("FR", "98713", True),
        ("RE", "97410", False),
    ],
)
async def test_renewal_uses_current_address_and_holds_blocked_territory(
    regular_user, monkeypatch, country, postal, held
):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(
        stripe.Customer, "retrieve", lambda *a, **kw: stripe_customer(country, postal)
    )
    monkeypatch.setattr("app.services.stripe_tax_service.dom_vat_rate_id", lambda: "txr_dom")
    modify = Mock()
    monkeypatch.setattr(stripe.Invoice, "modify", modify)
    async with test_session_factory() as db:
        account = (await db.scalars(select(Account))).one()
        account.stripe_customer_id = "cus_tax"
        await db.commit()
        await StripeService(db)._on_invoice_created(
            {
                "id": "in_renewal",
                "status": "draft",
                "customer": "cus_tax",
                "parent": {"subscription_details": {"subscription": "sub_tax"}},
            }
        )
    if held:
        modify.assert_called_once_with("in_renewal", auto_advance=False)
    else:
        assert modify.call_args.kwargs["default_tax_rates"] == ["txr_dom"]
        assert modify.call_args.kwargs["automatic_tax"] == {"enabled": False}
