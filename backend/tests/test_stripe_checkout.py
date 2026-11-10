"""Checkout API contract for Stripe 2026-10-28.endive; no real Stripe calls."""

import pytest
import stripe
from sqlalchemy import select

from app.core.config import settings
from app.models.account import Account
from tests.conftest import auth_header, test_session_factory


@pytest.mark.parametrize(
    ("path", "payload", "mode", "promotion_codes"),
    [
        ("/checkout", {"plan": "solo", "cycle": "monthly"}, "subscription", True),
        ("/checkout", {"plan": "solo", "cycle": "yearly"}, "subscription", False),
        ("/booster/checkout", None, "payment", None),
        ("/payment-method/update", None, "setup", None),
    ],
)
async def test_checkout_uses_dashboard_payment_methods(
    client, regular_user, monkeypatch, path, payload, mode, promotion_codes
):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_monthly")
    monkeypatch.setattr(settings, "stripe_price_solo_yearly", "price_yearly")
    monkeypatch.setattr(settings, "stripe_price_booster", "price_booster")
    async with test_session_factory() as db:
        account = (await db.scalars(select(Account))).one()
        account.stripe_customer_id = "cus_checkout_test"
        await db.commit()

    monkeypatch.setattr(stripe.Subscription, "list", lambda **kw: {"data": []})
    calls = []

    def create_session(**params):
        # This is the parameter rejected by Stripe in the production incident.
        if "payment_method_types" in params:
            raise stripe.InvalidRequestError("Unsupported parameter", "payment_method_types")
        calls.append(params)
        return {"id": "cs_test_checkout", "url": "https://checkout.stripe.com/test"}

    monkeypatch.setattr(stripe.checkout.Session, "create", create_session)
    response = await client.post(
        f"/api/v1/billing{path}",
        headers=auth_header(regular_user["token"]),
        json=payload,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "session_id": "cs_test_checkout",
        "checkout_url": "https://checkout.stripe.com/test",
    }
    assert len(calls) == 1
    params = calls[0]
    assert params["mode"] == mode
    assert params["customer"] == "cus_checkout_test"
    if mode == "subscription":
        assert params["allow_promotion_codes"] is promotion_codes
        expected_price = "price_monthly" if promotion_codes else "price_yearly"
        assert params["line_items"] == [{"price": expected_price, "quantity": 1}]
    if mode != "setup":
        assert params["automatic_tax"] == {"enabled": True}
        assert params["billing_address_collection"] == "required"
    else:
        assert params["setup_intent_data"]["metadata"]["purpose"] == "update_default_payment_method"
