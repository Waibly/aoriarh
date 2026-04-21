"""Stripe integration for commercial plans (Solo / Équipe / Groupe).

Handles:
  - creation/retrieval of a Stripe Customer per Account;
  - Checkout sessions (subscription mode for plans, payment mode for boosters);
  - Customer Portal sessions (self-service management);
  - webhook event dispatch that keeps our Subscription rows in sync with
    Stripe's state of truth.

Technical plans (gratuit / invite / vip) never touch this module — they
are assigned manually via the admin UI.
"""

import logging
import uuid
from datetime import UTC, datetime

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.plans import BOOSTER_QUESTIONS
from app.models.account import Account
from app.models.booster_purchase import BoosterPurchase
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


def _get(obj, key, default=None):
    """Safe dict-like accessor that works on both plain dicts and Stripe objects.

    The Stripe SDK returns ``StripeObject`` instances that support bracket
    indexing and ``in`` membership checks but **not** ``.get()``. Using
    ``.get()`` on them raises ``AttributeError: get``. This helper papers
    over the difference so webhook handlers can be written naturally.
    """
    try:
        if obj is None:
            return default
        if key in obj:
            return obj[key]
        return default
    except (TypeError, KeyError):
        return default


class StripeNotConfiguredError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Le module de paiement n'est pas encore configuré. "
                "Les clés Stripe et les identifiants de prix doivent être renseignés."
            ),
        )


class StripeService:
    """Thin wrapper around the Stripe SDK.

    All methods return Python types (never raw Stripe objects) so callers
    don't need to import `stripe` to use them.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._configure_stripe()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _configure_stripe() -> None:
        if not settings.stripe_secret_key:
            return
        stripe.api_key = settings.stripe_secret_key

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.stripe_secret_key)

    @staticmethod
    def _ensure_configured() -> None:
        if not StripeService.is_configured():
            raise StripeNotConfiguredError()

    # ------------------------------------------------------------------
    # Price mapping
    # ------------------------------------------------------------------

    @staticmethod
    def get_price_id(plan: str, cycle: str) -> str:
        mapping = {
            ("solo", "monthly"): settings.stripe_price_solo_monthly,
            ("solo", "yearly"): settings.stripe_price_solo_yearly,
            ("equipe", "monthly"): settings.stripe_price_equipe_monthly,
            ("equipe", "yearly"): settings.stripe_price_equipe_yearly,
            ("groupe", "monthly"): settings.stripe_price_groupe_monthly,
            ("groupe", "yearly"): settings.stripe_price_groupe_yearly,
        }
        price_id = mapping.get((plan, cycle), "")
        if not price_id:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=(
                    f"Tarif manquant en configuration : {plan} / {cycle}. "
                    "Renseignez l'identifiant Stripe correspondant dans .env."
                ),
            )
        return price_id

    @staticmethod
    def _success_url() -> str:
        return (
            settings.stripe_checkout_success_url
            or f"{settings.frontend_url}/settings/billing?success=1&session_id={{CHECKOUT_SESSION_ID}}"
        )

    @staticmethod
    def _cancel_url() -> str:
        return (
            settings.stripe_checkout_cancel_url
            or f"{settings.frontend_url}/settings/billing?canceled=1"
        )

    @staticmethod
    def _portal_return_url() -> str:
        return (
            settings.stripe_portal_return_url
            or f"{settings.frontend_url}/settings/billing"
        )

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    async def get_or_create_customer(self, account: Account, owner_email: str) -> str:
        """Return the Stripe customer ID for this account, creating one if needed."""
        self._ensure_configured()
        if account.stripe_customer_id:
            return account.stripe_customer_id

        customer = stripe.Customer.create(
            email=owner_email,
            name=account.name,
            metadata={"account_id": str(account.id)},
        )
        account.stripe_customer_id = customer["id"]
        await self.db.flush()
        logger.info(
            "Stripe customer created: %s for account %s", customer["id"], account.id
        )
        return customer["id"]

    # ------------------------------------------------------------------
    # Checkout sessions
    # ------------------------------------------------------------------

    async def create_subscription_checkout(
        self,
        account: Account,
        owner_email: str,
        plan: str,
        cycle: str,
    ) -> dict[str, str]:
        """Create a Stripe Checkout session for a commercial plan subscription."""
        self._ensure_configured()
        price_id = self.get_price_id(plan, cycle)
        customer_id = await self.get_or_create_customer(account, owner_email)

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=self._success_url(),
            cancel_url=self._cancel_url(),
            # Stripe Tax: automatic VAT calculation. Requires a billing
            # address (below) and at least one tax registration (FR).
            automatic_tax={"enabled": True},
            billing_address_collection="required",
            # Allow Stripe to update the existing customer's address/name
            # after the client enters them at checkout.
            customer_update={"address": "auto", "name": "auto"},
            # Let B2B customers enter their VAT number (reverse-charge when
            # they are in another EU country).
            tax_id_collection={"enabled": True},
            subscription_data={
                "metadata": {
                    "account_id": str(account.id),
                    "plan": plan,
                    "cycle": cycle,
                }
            },
            metadata={
                "account_id": str(account.id),
                "plan": plan,
                "cycle": cycle,
            },
        )
        await self.db.commit()
        return {"checkout_url": session["url"], "session_id": session["id"]}

    async def create_booster_checkout(
        self, account: Account, owner_email: str
    ) -> dict[str, str]:
        """One-shot payment for a +500 questions booster pack."""
        self._ensure_configured()
        if not settings.stripe_price_booster:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Pack booster non configuré (STRIPE_PRICE_BOOSTER manquant).",
            )
        customer_id = await self.get_or_create_customer(account, owner_email)

        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer_id,
            line_items=[{"price": settings.stripe_price_booster, "quantity": 1}],
            success_url=self._success_url(),
            cancel_url=self._cancel_url(),
            # Same tax settings as the subscription flow so the VAT is
            # calculated consistently for the booster purchase.
            automatic_tax={"enabled": True},
            billing_address_collection="required",
            customer_update={"address": "auto", "name": "auto"},
            tax_id_collection={"enabled": True},
            metadata={
                "account_id": str(account.id),
                "product": "booster",
            },
            payment_intent_data={
                "metadata": {
                    "account_id": str(account.id),
                    "product": "booster",
                }
            },
        )
        await self.db.commit()
        return {"checkout_url": session["url"], "session_id": session["id"]}

    async def create_portal_session(self, account: Account) -> str:
        """Create a Customer Portal session. Account must have a Stripe customer."""
        self._ensure_configured()
        if not account.stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ce compte n'a pas encore de souscription payante.",
            )
        session = stripe.billing_portal.Session.create(
            customer=account.stripe_customer_id,
            return_url=self._portal_return_url(),
        )
        return session["url"]

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    @staticmethod
    def verify_webhook(payload: bytes, signature: str) -> dict:
        """Verify and parse a Stripe webhook payload.

        Raises HTTPException(400) if the signature or payload is invalid.
        """
        if not settings.stripe_webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="STRIPE_WEBHOOK_SECRET manquant en configuration.",
            )
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.stripe_webhook_secret
            )
        except (ValueError, stripe.error.SignatureVerificationError) as exc:
            logger.warning("Stripe webhook verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Signature Stripe invalide.",
            ) from exc
        return event

    async def handle_webhook_event(self, event: dict) -> None:
        """Dispatch a verified Stripe event to the appropriate handler."""
        event_type = event["type"]
        data = event["data"]["object"]

        logger.info("Stripe webhook received: %s", event_type)

        handlers = {
            "checkout.session.completed": self._on_checkout_completed,
            "customer.subscription.created": self._on_subscription_updated,
            "customer.subscription.updated": self._on_subscription_updated,
            "customer.subscription.deleted": self._on_subscription_deleted,
            "invoice.paid": self._on_invoice_paid,
            "invoice.payment_failed": self._on_invoice_payment_failed,
        }
        handler = handlers.get(event_type)
        if handler is None:
            logger.debug("Stripe event ignored: %s", event_type)
            return
        await handler(data)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Webhook handlers
    # ------------------------------------------------------------------

    async def _on_checkout_completed(self, session: dict) -> None:
        """Checkout complete: flip the account to the new plan, persist Subscription or Booster."""
        meta = _get(session, "metadata") or {}
        account_id = _get(meta, "account_id")
        if not account_id:
            logger.warning("checkout.session.completed without account_id metadata")
            return
        account = await self.db.get(Account, uuid.UUID(account_id))
        if account is None:
            logger.warning("Account %s not found for checkout session", account_id)
            return

        mode = _get(session, "mode")
        if mode == "subscription":
            await self._create_or_update_subscription_from_checkout(account, session)
        elif mode == "payment":
            await self._create_booster_from_checkout(account, session)

    async def _create_or_update_subscription_from_checkout(
        self, account: Account, session: dict
    ) -> None:
        stripe_subscription_id = _get(session, "subscription")
        if not stripe_subscription_id:
            return
        meta = _get(session, "metadata") or {}
        plan = _get(meta, "plan")
        cycle = _get(meta, "cycle")

        # Fetch full subscription to read period dates
        sub_obj = stripe.Subscription.retrieve(stripe_subscription_id)

        # Look up existing local row (rare — usually a fresh one)
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            sub = Subscription(
                account_id=account.id,
                plan=plan or "solo",
                billing_cycle=cycle or "monthly",
                status=sub_obj["status"],
                stripe_subscription_id=stripe_subscription_id,
            )
            self.db.add(sub)

        sub.status = sub_obj["status"]
        sub.current_period_start = _ts_to_dt(_get(sub_obj, "current_period_start"))
        sub.current_period_end = _ts_to_dt(_get(sub_obj, "current_period_end"))
        sub.cancel_at_period_end = bool(_get(sub_obj, "cancel_at_period_end"))

        # Mirror onto the Account
        account.plan = plan or account.plan
        account.status = "active" if sub_obj["status"] in ("active", "trialing") else account.status
        account.plan_assigned_at = datetime.now(UTC)
        account.plan_expires_at = None  # commercial plans don't expire unless canceled

        await self.db.flush()

    async def _create_booster_from_checkout(
        self, account: Account, session: dict
    ) -> None:
        payment_intent_id = _get(session, "payment_intent")
        amount_total = _get(session, "amount_total", 0)

        # No time-based expiry: booster questions stay available until consumed.
        # The monthly quota is always consumed first (see
        # BillingService.increment_question_count), so a booster is only
        # touched in months where the user exceeds the included quota.
        # The `expires_at` column is kept on the model for future use
        # (promotional boosters with a shelf life).
        expires_at: datetime | None = None

        # Deduplicate: if a BoosterPurchase already exists for this payment_intent, skip
        if payment_intent_id:
            result = await self.db.execute(
                select(BoosterPurchase).where(
                    BoosterPurchase.stripe_payment_intent_id == payment_intent_id
                )
            )
            if result.scalar_one_or_none() is not None:
                return

        booster = BoosterPurchase(
            account_id=account.id,
            questions_purchased=BOOSTER_QUESTIONS,
            questions_remaining=BOOSTER_QUESTIONS,
            price_cents=int(amount_total or 0),
            stripe_payment_intent_id=payment_intent_id,
            purchased_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        self.db.add(booster)
        await self.db.flush()

    async def _on_subscription_updated(self, sub_obj: dict) -> None:
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub_obj["id"]
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            # Subscription not yet known locally (can happen if webhook arrives
            # before checkout.session.completed). Create a placeholder.
            meta = _get(sub_obj, "metadata") or {}
            account_id_meta = _get(meta, "account_id")
            if not account_id_meta:
                return
            sub = Subscription(
                account_id=uuid.UUID(account_id_meta),
                plan=_get(meta, "plan", "solo"),
                billing_cycle=_get(meta, "cycle", "monthly"),
                status=sub_obj["status"],
                stripe_subscription_id=sub_obj["id"],
            )
            self.db.add(sub)

        sub.status = sub_obj["status"]
        sub.current_period_start = _ts_to_dt(_get(sub_obj, "current_period_start"))
        sub.current_period_end = _ts_to_dt(_get(sub_obj, "current_period_end"))
        sub.cancel_at_period_end = bool(_get(sub_obj, "cancel_at_period_end"))
        canceled_at = _get(sub_obj, "canceled_at")
        if canceled_at:
            sub.canceled_at = _ts_to_dt(canceled_at)

        # Sync the Account status on known bad states
        account = await self.db.get(Account, sub.account_id)
        if account is None:
            return
        if sub_obj["status"] == "past_due":
            account.status = "past_due"
        elif sub_obj["status"] in ("active", "trialing"):
            account.status = "active"

        await self.db.flush()

    async def _on_subscription_deleted(self, sub_obj: dict) -> None:
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub_obj["id"]
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        sub.status = "canceled"
        sub.canceled_at = datetime.now(UTC)

        account = await self.db.get(Account, sub.account_id)
        if account is not None:
            account.status = "canceled"

        await self.db.flush()

    async def _on_invoice_paid(self, invoice: dict) -> None:
        """On a successful renewal, bring the account back to 'active'."""
        stripe_subscription_id = _get(invoice, "subscription")
        if not stripe_subscription_id:
            return
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        sub.status = "active"
        account = await self.db.get(Account, sub.account_id)
        if account is not None and account.status == "past_due":
            account.status = "active"
        await self.db.flush()

    async def _on_invoice_payment_failed(self, invoice: dict) -> None:
        stripe_subscription_id = _get(invoice, "subscription")
        if not stripe_subscription_id:
            return
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == stripe_subscription_id
            )
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        sub.status = "past_due"
        attempt_count = int(_get(invoice, "attempt_count") or 0)
        account = await self.db.get(Account, sub.account_id)
        if account is None:
            return
        # After 2 consecutive failures, suspend access until regularised.
        if attempt_count >= 2:
            account.status = "suspended"
        else:
            account.status = "past_due"
        await self.db.flush()

    async def _latest_subscription(
        self, account_id: uuid.UUID
    ) -> Subscription | None:
        result = await self.db.execute(
            select(Subscription)
            .where(Subscription.account_id == account_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=UTC)
