"""Stripe billing lifecycle: access, unpaid invoices, refunds, yearly quota.

Stripe is never contacted: the SDK calls used by each flow are patched. The
webhook payloads follow API 2026-03-25.dahlia (our live webhook version), where
``invoice.subscription`` and ``charge.invoice`` no longer exist.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import stripe
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.models.account import Account
from app.models.booster_purchase import BoosterPurchase
from app.models.stripe_webhook_event import StripeWebhookEvent
from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon
from app.models.user import User
from app.services.billing_service import BillingService, _monthly_window
from app.services.stripe_service import StripeService
from tests.conftest import auth_header, test_session_factory

SUB_ID = "sub_test_1"


@pytest.fixture(autouse=True)
def _no_stripe_network(monkeypatch):
    # Not configured → no subscription refresh from the network.
    monkeypatch.setattr(settings, "stripe_secret_key", "")


async def _paid_account(email: str, *, plan="solo", cycle="monthly", status="active"):
    async with test_session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        account = (
            await session.execute(select(Account).where(Account.owner_id == user.id))
        ).scalar_one()
        account.plan = plan
        account.status = "active"
        account.plan_expires_at = None
        account.stripe_customer_id = "cus_test"
        now = datetime.now(UTC)
        session.add(
            Subscription(
                account_id=account.id,
                plan=plan,
                billing_cycle=cycle,
                status=status,
                stripe_subscription_id=SUB_ID,
                current_period_start=now - timedelta(days=3),
                current_period_end=now + timedelta(days=27),
            )
        )
        await session.commit()
        return account.id


async def _account(account_id) -> Account:
    async with test_session_factory() as session:
        return await session.get(Account, account_id)


def _dahlia_invoice(attempt_count=1):
    return {
        "id": "in_1",
        "attempt_count": attempt_count,
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": SUB_ID},
        },
    }


async def _deliver(event_type, obj, event_id=None):
    async with test_session_factory() as session:
        await StripeService(session).handle_webhook_event(
            {
                "id": event_id or f"evt_{uuid.uuid4().hex}",
                "type": event_type,
                "data": {"object": obj},
            }
        )


# ---------------------------------------------------------------------------
# Access after cancellation
# ---------------------------------------------------------------------------


async def test_canceled_subscription_cuts_access(regular_user):
    account_id = await _paid_account(regular_user["email"])

    await _deliver("customer.subscription.deleted", {"id": SUB_ID, "status": "canceled"})

    account = await _account(account_id)
    assert account.status == "canceled"
    with pytest.raises(HTTPException) as exc:
        BillingService(None).ensure_plan_active(account)
    assert exc.value.status_code == 402


async def test_canceled_account_still_sees_billing_page(client: AsyncClient, regular_user):
    await _paid_account(regular_user["email"])
    await _deliver("customer.subscription.deleted", {"id": SUB_ID, "status": "canceled"})

    headers = auth_header(regular_user["token"])
    quota = await client.get("/api/v1/billing/quota", headers=headers)
    usage = await client.get("/api/v1/billing/usage-summary", headers=headers)

    assert quota.status_code == 200
    assert quota.json()["status"] == "canceled"
    assert usage.status_code == 200


async def test_expired_trial_still_sees_billing_page(client: AsyncClient, regular_user):
    async with test_session_factory() as session:
        await session.execute(
            update(Account).values(
                status="suspended", plan_expires_at=datetime.now(UTC) - timedelta(days=1)
            )
        )
        await session.commit()

    response = await client.get("/api/v1/billing/quota", headers=auth_header(regular_user["token"]))

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"


async def test_late_cancel_event_does_not_cut_admin_assigned_vip(regular_user):
    account_id = await _paid_account(regular_user["email"])
    async with test_session_factory() as session:
        await session.execute(update(Account).values(plan="vip", status="active"))
        await session.commit()

    await _deliver("customer.subscription.deleted", {"id": SUB_ID, "status": "canceled"})

    assert (await _account(account_id)).status == "active"


async def test_deleted_after_scheduled_cancel_sends_no_second_email(regular_user, monkeypatch):
    await _paid_account(regular_user["email"])
    async with test_session_factory() as session:
        await session.execute(update(Subscription).values(cancel_at_period_end=True))
        await session.commit()
    sent = []

    async def fake_email(self, account, sub):
        sent.append(sub.id)

    monkeypatch.setattr(StripeService, "_send_subscription_canceled_email", fake_email)

    await _deliver("customer.subscription.deleted", {"id": SUB_ID, "status": "canceled"})

    assert sent == []


# ---------------------------------------------------------------------------
# Unpaid invoices (dahlia payloads)
# ---------------------------------------------------------------------------


async def test_repeated_payment_failure_suspends_then_payment_restores(regular_user):
    account_id = await _paid_account(regular_user["email"])

    await _deliver("invoice.payment_failed", _dahlia_invoice(attempt_count=1))
    assert (await _account(account_id)).status == "past_due"

    await _deliver("invoice.payment_failed", _dahlia_invoice(attempt_count=2))
    assert (await _account(account_id)).status == "suspended"

    # A later subscription.updated still in past_due must keep the suspension.
    await _deliver(
        "customer.subscription.updated",
        {"id": SUB_ID, "status": "past_due", "items": {"data": []}},
    )
    assert (await _account(account_id)).status == "suspended"

    await _deliver("invoice.paid", _dahlia_invoice())
    assert (await _account(account_id)).status == "active"


async def test_unpaid_subscription_suspends(regular_user):
    account_id = await _paid_account(regular_user["email"])

    await _deliver(
        "customer.subscription.updated",
        {"id": SUB_ID, "status": "unpaid", "items": {"data": []}},
    )

    assert (await _account(account_id)).status == "suspended"


async def test_redelivered_event_is_processed_once(regular_user, monkeypatch):
    await _paid_account(regular_user["email"])
    sent = []

    async def fake_email(self, account, sub):
        sent.append(sub.id)

    monkeypatch.setattr(StripeService, "_send_subscription_canceled_email", fake_email)
    obj = {"id": SUB_ID, "status": "active", "cancel_at_period_end": True, "items": {"data": []}}

    await _deliver("customer.subscription.updated", obj, event_id="evt_same")
    async with test_session_factory() as session:
        await session.execute(update(Subscription).values(cancel_at_period_end=False))
        await session.commit()
    await _deliver("customer.subscription.updated", obj, event_id="evt_same")

    assert len(sent) == 1
    async with test_session_factory() as session:
        assert await session.get(StripeWebhookEvent, "evt_same") is not None


# ---------------------------------------------------------------------------
# Refunds (dahlia: charge → InvoicePayment → invoice → subscription)
# ---------------------------------------------------------------------------


async def test_full_refund_of_subscription_cancels_access(regular_user, monkeypatch):
    account_id = await _paid_account(regular_user["email"])
    canceled = []
    monkeypatch.setattr(
        stripe.InvoicePayment,
        "list",
        lambda **kw: (
            {"data": [{"invoice": "in_1"}]}
            if kw["payment"]["payment_intent"] == "pi_sub"
            else {"data": []}
        ),
    )
    monkeypatch.setattr(stripe.Invoice, "retrieve", lambda _id: _dahlia_invoice())
    monkeypatch.setattr(stripe.Subscription, "cancel", lambda sid: canceled.append(sid))

    await _deliver(
        "charge.refunded",
        {"id": "ch_1", "amount": 9480, "amount_refunded": 9480, "payment_intent": "pi_sub"},
    )

    assert canceled == [SUB_ID]
    assert (await _account(account_id)).status == "canceled"


async def test_full_refund_of_booster_zeroes_questions(regular_user):
    account_id = await _paid_account(regular_user["email"])
    async with test_session_factory() as session:
        session.add(
            BoosterPurchase(
                account_id=account_id,
                questions_purchased=500,
                questions_remaining=420,
                price_cents=4900,
                stripe_payment_intent_id="pi_boost",
                purchased_at=datetime.now(UTC),
            )
        )
        await session.commit()

    await _deliver(
        "charge.refunded",
        {"id": "ch_2", "amount": 4900, "amount_refunded": 4900, "payment_intent": "pi_boost"},
    )

    async with test_session_factory() as session:
        booster = (await session.execute(select(BoosterPurchase))).scalar_one()
        assert booster.questions_remaining == 0
    assert (await _account(account_id)).status == "active"


# ---------------------------------------------------------------------------
# Yearly subscription: the quota stays monthly
# ---------------------------------------------------------------------------


def test_yearly_period_is_sliced_into_months():
    start = datetime(2026, 1, 31, 10, tzinfo=UTC)
    end = datetime(2027, 1, 31, 10, tzinfo=UTC)

    window = _monthly_window(start, end, datetime(2026, 3, 15, tzinfo=UTC))

    assert window == (datetime(2026, 2, 28, 10, tzinfo=UTC), datetime(2026, 3, 31, 10, tzinfo=UTC))


def test_monthly_period_is_unchanged():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    end = datetime(2026, 12, 1, tzinfo=UTC)

    assert _monthly_window(start, end, datetime(2026, 11, 20, tzinfo=UTC)) == (start, end)


async def test_yearly_subscriber_gets_a_monthly_window(regular_user):
    account_id = await _paid_account(regular_user["email"], cycle="yearly")
    now = datetime.now(UTC)
    async with test_session_factory() as session:
        await session.execute(
            update(Subscription).values(
                current_period_start=now - timedelta(days=100),
                current_period_end=now + timedelta(days=265),
            )
        )
        await session.commit()

    async with test_session_factory() as session:
        account = await session.get(Account, account_id)
        start, end = await BillingService(session)._current_period(account)

    assert start <= now < end
    assert end - start <= timedelta(days=31)


# ---------------------------------------------------------------------------
# No second subscription, no silent add-on removal
# ---------------------------------------------------------------------------


async def test_second_checkout_is_refused(regular_user, monkeypatch):
    account_id = await _paid_account(regular_user["email"])
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_equipe_monthly", "price_equipe")
    created = []
    monkeypatch.setattr(stripe.checkout.Session, "create", lambda **kw: created.append(kw))

    async with test_session_factory() as session:
        account = await session.get(Account, account_id)
        with pytest.raises(HTTPException) as exc:
            await StripeService(session).create_subscription_checkout(
                account, "user@test.com", "equipe", "monthly"
            )

    assert exc.value.status_code == 409
    assert created == []


async def test_checkout_refused_when_stripe_has_a_sub_not_yet_mirrored(regular_user, monkeypatch):
    account_id = await _paid_account(regular_user["email"])
    async with test_session_factory() as session:
        await session.execute(update(Subscription).values(status="canceled"))
        await session.commit()
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_price_solo_monthly", "price_solo")
    monkeypatch.setattr(
        stripe.Subscription, "list", lambda **kw: {"data": [{"id": "sub_new", "status": "active"}]}
    )
    created = []
    monkeypatch.setattr(stripe.checkout.Session, "create", lambda **kw: created.append(kw))

    async with test_session_factory() as session:
        account = await session.get(Account, account_id)
        with pytest.raises(HTTPException) as exc:
            await StripeService(session).create_subscription_checkout(
                account, "user@test.com", "solo", "monthly"
            )

    assert exc.value.status_code == 409
    assert created == []


async def test_addon_kept_when_stripe_removal_fails(regular_user, monkeypatch):
    account_id = await _paid_account(regular_user["email"])
    async with test_session_factory() as session:
        sub = (await session.execute(select(Subscription))).scalar_one()
        addon = SubscriptionAddon(
            subscription_id=sub.id,
            addon_type="extra_org",
            quantity=1,
            unit_price_cents=1900,
            stripe_subscription_item_id="si_1",
        )
        session.add(addon)
        await session.commit()
        addon_id = addon.id
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")

    def fail(*args, **kwargs):
        raise stripe.error.APIConnectionError("down")

    monkeypatch.setattr(stripe.SubscriptionItem, "delete", fail)

    async with test_session_factory() as session:
        account = await session.get(Account, account_id)
        with pytest.raises(HTTPException) as exc:
            await StripeService(session).remove_addon(account, addon_id)

    assert exc.value.status_code == 502
    async with test_session_factory() as session:
        assert await session.get(SubscriptionAddon, addon_id) is not None


async def test_incomplete_checkout_does_not_lift_trial(regular_user, monkeypatch):
    async with test_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == regular_user["email"]))
        ).scalar_one()
        account = (
            await session.execute(select(Account).where(Account.owner_id == user.id))
        ).scalar_one()
        trial_end = account.plan_expires_at
        account_id = account.id
    monkeypatch.setattr(
        stripe.Subscription,
        "retrieve",
        lambda sid: {"id": sid, "status": "incomplete", "items": {"data": []}},
    )

    await _deliver(
        "checkout.session.completed",
        {
            "mode": "subscription",
            "subscription": SUB_ID,
            "metadata": {"account_id": str(account_id), "plan": "solo", "cycle": "monthly"},
        },
    )

    account = await _account(account_id)
    assert account.plan == "gratuit"
    assert account.plan_expires_at == trial_end

    # The payment is confirmed later: the account becomes paid.
    await _deliver(
        "customer.subscription.updated",
        {"id": SUB_ID, "status": "active", "items": {"data": []}},
    )
    account = await _account(account_id)
    assert account.plan == "solo"
    assert account.status == "active"
    assert account.plan_expires_at is None


def test_invoice_subscription_id_reads_legacy_and_dahlia_shapes():
    from app.services.stripe_service import _invoice_subscription_id

    assert _invoice_subscription_id({"subscription": "sub_old"}) == "sub_old"
    assert _invoice_subscription_id(_dahlia_invoice()) == SUB_ID
    assert _invoice_subscription_id({"parent": None}) is None
    assert _invoice_subscription_id(SimpleNamespace()) is None


# ---------------------------------------------------------------------------
# Through the real HTTP route, with a Stripe signature
# ---------------------------------------------------------------------------


def _signed(payload: str, secret: str) -> str:
    import hashlib
    import hmac
    import time

    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


async def test_signed_webhook_suspends_unpaid_account(
    client: AsyncClient, regular_user, monkeypatch
):
    import json

    account_id = await _paid_account(regular_user["email"])
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    event = {
        "id": "evt_http_1",
        "object": "event",
        "api_version": "2026-03-25.dahlia",
        "type": "invoice.payment_failed",
        "data": {"object": {"object": "invoice", **_dahlia_invoice(attempt_count=2)}},
    }
    payload = json.dumps(event)

    bad = await client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": _signed(payload, "whsec_wrong")},
    )
    assert bad.status_code == 400
    assert (await _account(account_id)).status == "active"

    ok = await client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": _signed(payload, "whsec_test")},
    )
    assert ok.status_code == 200
    assert (await _account(account_id)).status == "suspended"

    again = await client.post(
        "/api/v1/billing/webhook",
        content=payload,
        headers={"stripe-signature": _signed(payload, "whsec_test")},
    )
    assert again.status_code == 200
