"""Stripe SDK 16 returns StripeObject instances, not dicts.

Production incident of 2026-11-10: ``inv.get("number")`` raised
``AttributeError`` on the invoices page because the tests mocked Stripe with
plain dicts. Every mocked Stripe response here is built with
``construct_from``, the same type the SDK returns in production.
"""

import pytest
import stripe

from app.core.config import settings
from tests.conftest import auth_header
from tests.test_stripe_lifecycle import SUB_ID, _paid_account


def _obj(data: dict, cls=stripe.StripeObject):
    return cls.construct_from(data, "sk_test_fake")


def test_stripe_objects_have_no_dict_get():
    # Guard: if a future SDK restores .get(), this documents why the code
    # still goes through _get(); if it fails, the premise of these tests moved.
    with pytest.raises(AttributeError):
        _obj({"id": "x"}).get("id")


async def test_invoice_list_reads_sdk_objects(client, regular_user, monkeypatch):
    await _paid_account(regular_user["email"])
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    invoice = _obj(
        {
            "id": "in_1",
            "object": "invoice",
            "number": "E8RAPN2X-0002",
            "status": "paid",
            "amount_paid": 7900,
            "amount_due": 7900,
            "currency": "eur",
            "created": 1794313778,
            "hosted_invoice_url": "https://invoice.stripe.com/i/1",
            "invoice_pdf": "https://pay.stripe.com/invoice/1/pdf",
        },
        stripe.Invoice,
    )
    listing = _obj({"object": "list", "data": [invoice], "has_more": False}, stripe.ListObject)
    monkeypatch.setattr(stripe.Invoice, "list", lambda **kw: listing)

    response = await client.get(
        "/api/v1/billing/invoices", headers=auth_header(regular_user["token"])
    )

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": "in_1",
            "number": "E8RAPN2X-0002",
            "status": "paid",
            "amount_paid_cents": 7900,
            "amount_due_cents": 7900,
            "currency": "eur",
            "created": 1794313778,
            "hosted_invoice_url": "https://invoice.stripe.com/i/1",
            "invoice_pdf": "https://pay.stripe.com/invoice/1/pdf",
        }
    ]


async def test_change_plan_preview_reads_total_taxes(client, regular_user, monkeypatch):
    await _paid_account(regular_user["email"])
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_solo_m")
    monkeypatch.setattr(settings, "stripe_price_equipe_monthly", "price_equipe_m")
    remote_sub = _obj(
        {
            "id": SUB_ID,
            "object": "subscription",
            "items": {
                "object": "list",
                "data": [{"id": "si_plan", "price": {"id": "price_solo_m"}}],
            },
        },
        stripe.Subscription,
    )
    monkeypatch.setattr(stripe.Subscription, "retrieve", lambda *a, **kw: remote_sub)
    # API 2026-10-28.endive: no "tax" field, one entry per rate in total_taxes.
    preview = _obj(
        {
            "object": "invoice",
            "amount_due": 21894,
            "subtotal": 18245,
            "currency": "eur",
            "period_end": 1796905778,
            "total_taxes": [{"amount": 3000}, {"amount": 649}],
        },
        stripe.Invoice,
    )
    monkeypatch.setattr(stripe.Invoice, "create_preview", lambda **kw: preview)

    response = await client.post(
        "/api/v1/billing/preview-change-plan",
        headers=auth_header(regular_user["token"]),
        json={"plan": "equipe", "cycle": "monthly"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["amount_due_cents"] == 21894
    assert body["amount_tax_cents"] == 3649
    assert body["amount_subtotal_cents"] == 18245


def test_invoice_tax_falls_back_on_legacy_field():
    from app.services.stripe_service import _invoice_tax_cents

    assert _invoice_tax_cents({"tax": 1316}) == 1316
    assert _invoice_tax_cents(_obj({"total_taxes": []})) == 0


async def test_stripe_refusal_returns_502_not_500(client, regular_user, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_monthly")
    monkeypatch.setattr(
        stripe.Customer, "create", lambda **kw: _obj({"id": "cus_new"}, stripe.Customer)
    )

    def refuse(**params):
        raise stripe.InvalidRequestError("Unsupported parameter", "some_param")

    monkeypatch.setattr(stripe.checkout.Session, "create", refuse)

    response = await client.post(
        "/api/v1/billing/checkout",
        headers=auth_header(regular_user["token"]),
        json={"plan": "solo", "cycle": "monthly"},
    )

    assert response.status_code == 502
    assert "paiement" in response.json()["detail"]
