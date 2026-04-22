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
from app.core.plans import BOOSTER_QUESTIONS, get_label as _get_plan_label
from app.models.account import Account
from app.models.booster_purchase import BoosterPurchase
from app.models.subscription import Subscription
from app.models.subscription_addon import SubscriptionAddon

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


def _sub_period(sub_obj) -> tuple[int | None, int | None]:
    """Return (current_period_start, current_period_end) for a Stripe sub.

    Starting with Stripe API 2024-12+, these fields moved from the root
    Subscription object to the individual SubscriptionItems. We probe both
    so the code survives any API version bump.
    """
    start = _get(sub_obj, "current_period_start")
    end = _get(sub_obj, "current_period_end")
    if start and end:
        return start, end
    items = _get(sub_obj, "items")
    data = _get(items, "data") if items is not None else None
    if data:
        first = data[0]
        return (
            _get(first, "current_period_start") or start,
            _get(first, "current_period_end") or end,
        )
    return start, end


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
            # Only accept credit/debit cards. Even if the Stripe dashboard
            # is ever reconfigured to enable wallets or SEPA, our checkout
            # stays card-only — simpler accounting, zero async payment
            # flow to monitor.
            payment_method_types=["card"],
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
            # Card-only — consistent with the subscription checkout.
            payment_method_types=["card"],
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

    # ------------------------------------------------------------------
    # Add-ons (user, org, docs) — self-service from /billing
    # ------------------------------------------------------------------

    _ADDON_PRICE_ATTR = {
        "extra_user": "stripe_price_addon_user",
        "extra_org": "stripe_price_addon_org",
        "extra_docs": "stripe_price_addon_docs",
    }
    _ADDON_UNIT_PRICE_CENTS = {
        "extra_user": 1500,
        "extra_org": 1900,
        "extra_docs": 1000,
    }

    async def _get_active_subscription(
        self, account_id: uuid.UUID
    ) -> Subscription | None:
        """Return the commercial subscription currently active for an account.

        Mirrors BillingService._get_active_subscription — duplicated here so
        add_addon/remove_addon can locate the Stripe-linked sub without
        circular imports between the two services.
        """
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.account_id == account_id,
                Subscription.status.in_(["active", "trialing", "past_due"]),
            )
        )
        return result.scalars().first()

    async def change_plan(
        self, account: Account, new_plan: str, new_cycle: str
    ) -> dict[str, str]:
        """Modify the current Stripe subscription to a different plan/cycle.

        Locates the main subscription item (the non-addon one), swaps its
        price to the new plan, and lets Stripe prorate the charge. The
        ``customer.subscription.updated`` webhook will mirror the change
        on our local rows.

        For downgrades, we pre-flight ``_validate_plan_fits_existing_data``
        and return 409 if the target plan is too small for the current
        data — we block rather than leave the account in overflow.
        """
        self._ensure_configured()
        sub = await self._get_active_subscription(account.id)
        if sub is None or not sub.stripe_subscription_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Aucune souscription active à modifier. "
                    "Souscrivez d'abord un plan via la page tarifs."
                ),
            )
        if sub.plan == new_plan and sub.billing_cycle == new_cycle:
            raise HTTPException(
                status_code=400,
                detail="Ce plan et ce cycle sont déjà actifs.",
            )

        new_price_id = self.get_price_id(new_plan, new_cycle)

        # Block downgrades that would leave the account in overflow.
        order = ["solo", "equipe", "groupe"]
        if (
            sub.plan in order
            and new_plan in order
            and order.index(new_plan) < order.index(sub.plan)
        ):
            from app.services.plan_service import (
                PlanOverflowError,
                _validate_plan_fits_existing_data,
            )
            try:
                await _validate_plan_fits_existing_data(self.db, account.id, new_plan)
            except PlanOverflowError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Downgrade bloqué : le plan visé ne couvre pas les données "
                        "existantes. " + " • ".join(exc.reasons)
                    ),
                ) from exc

        # Identify the plan subscription item: anything that is not a known
        # add-on item. We store add-on item IDs locally, so the odd one out
        # is the plan itself.
        addon_rows = await self.db.execute(
            select(SubscriptionAddon).where(
                SubscriptionAddon.subscription_id == sub.id
            )
        )
        addon_item_ids = {
            a.stripe_subscription_item_id
            for a in addon_rows.scalars()
            if a.stripe_subscription_item_id
        }

        stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)
        plan_item_id: str | None = None
        for item in stripe_sub["items"]["data"]:
            if item["id"] not in addon_item_ids:
                plan_item_id = item["id"]
                break
        if plan_item_id is None:
            raise HTTPException(
                status_code=500,
                detail="Impossible de localiser la ligne d'abonnement principale.",
            )

        stripe.Subscription.modify(
            sub.stripe_subscription_id,
            items=[{"id": plan_item_id, "price": new_price_id}],
            proration_behavior="create_prorations",
        )
        # Mirror immediately so the UI reflects the change before the webhook
        # round-trip completes. The webhook will confirm / reconcile.
        sub.plan = new_plan
        sub.billing_cycle = new_cycle
        account.plan = new_plan
        await self.db.commit()
        return {
            "plan": new_plan,
            "cycle": new_cycle,
            "stripe_subscription_id": sub.stripe_subscription_id,
        }

    async def add_addon(
        self, account: Account, addon_type: str, delta: int = 1
    ) -> SubscriptionAddon:
        """Increment the quantity of a recurring add-on on the active sub.

        If no Stripe subscription item of that type exists yet, create one.
        Otherwise just bump quantity. Also maintains the local
        SubscriptionAddon row in parallel.
        """
        self._ensure_configured()
        if addon_type not in self._ADDON_PRICE_ATTR:
            raise HTTPException(
                status_code=400, detail=f"Add-on type inconnu : {addon_type}"
            )
        price_id = getattr(settings, self._ADDON_PRICE_ATTR[addon_type], "")
        if not price_id:
            raise HTTPException(
                status_code=501,
                detail=f"Add-on {addon_type} non configuré (price ID manquant)",
            )

        sub = await self._get_active_subscription(account.id)
        if sub is None or not sub.stripe_subscription_id:
            raise HTTPException(
                status_code=400,
                detail="Aucune souscription active — les add-ons nécessitent un plan commercial.",
            )

        # Look for an existing SubscriptionAddon of this type
        result = await self.db.execute(
            select(SubscriptionAddon).where(
                SubscriptionAddon.subscription_id == sub.id,
                SubscriptionAddon.addon_type == addon_type,
            )
        )
        existing = result.scalar_one_or_none()

        stripe_sub = stripe.Subscription.retrieve(sub.stripe_subscription_id)

        if existing and existing.stripe_subscription_item_id:
            # Bump quantity on the Stripe side and mirror locally.
            new_qty = existing.quantity + delta
            if new_qty <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Utilisez la suppression pour retirer complètement cet add-on.",
                )
            stripe.SubscriptionItem.modify(
                existing.stripe_subscription_item_id,
                quantity=new_qty,
                proration_behavior="create_prorations",
            )
            existing.quantity = new_qty
            await self.db.flush()
            await self.db.commit()
            return existing

        # Otherwise: add a brand new item to the subscription.
        updated = stripe.Subscription.modify(
            sub.stripe_subscription_id,
            items=[{"price": price_id, "quantity": delta}],
            proration_behavior="create_prorations",
        )
        # Find the newly-added subscription item (match by price id).
        new_item_id: str | None = None
        for item in updated["items"]["data"]:
            if item["price"]["id"] == price_id:
                new_item_id = item["id"]
                break

        addon = SubscriptionAddon(
            subscription_id=sub.id,
            addon_type=addon_type,
            quantity=delta,
            unit_price_cents=self._ADDON_UNIT_PRICE_CENTS[addon_type],
            stripe_subscription_item_id=new_item_id,
        )
        self.db.add(addon)
        await self.db.flush()
        await self.db.commit()
        return addon

    async def remove_addon(self, account: Account, addon_id: uuid.UUID) -> None:
        """Delete a SubscriptionAddon row and remove its Stripe counterpart."""
        self._ensure_configured()
        addon = await self.db.get(SubscriptionAddon, addon_id)
        if addon is None:
            raise HTTPException(status_code=404, detail="Add-on non trouvé")

        sub = await self.db.get(Subscription, addon.subscription_id)
        if sub is None or sub.account_id != account.id:
            raise HTTPException(status_code=403, detail="Add-on non lié à ce compte")

        if addon.stripe_subscription_item_id:
            try:
                stripe.SubscriptionItem.delete(
                    addon.stripe_subscription_item_id,
                    proration_behavior="create_prorations",
                )
            except stripe.error.StripeError:
                logger.exception(
                    "Stripe item deletion failed for %s — removing local row anyway",
                    addon.stripe_subscription_item_id,
                )

        await self.db.delete(addon)
        await self.db.commit()

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
            # SEPA / bank debits: the checkout returns before the payment
            # actually clears. This second event fires 3-5 days later when
            # the money is in. We treat it identically to .completed.
            "checkout.session.async_payment_succeeded": self._on_checkout_completed,
            "checkout.session.expired": self._on_checkout_expired,
            "customer.subscription.created": self._on_subscription_updated,
            "customer.subscription.updated": self._on_subscription_updated,
            "customer.subscription.deleted": self._on_subscription_deleted,
            "invoice.paid": self._on_invoice_paid,
            "invoice.payment_failed": self._on_invoice_payment_failed,
            "charge.refunded": self._on_charge_refunded,
            "customer.tax_id.created": self._on_tax_id_changed,
            "customer.tax_id.updated": self._on_tax_id_changed,
            "customer.tax_id.deleted": self._on_tax_id_changed,
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
        _start, _end = _sub_period(sub_obj)
        sub.current_period_start = _ts_to_dt(_start)
        sub.current_period_end = _ts_to_dt(_end)
        sub.cancel_at_period_end = bool(_get(sub_obj, "cancel_at_period_end"))

        # Mirror onto the Account
        account.plan = plan or account.plan
        account.status = "active" if sub_obj["status"] in ("active", "trialing") else account.status
        account.plan_assigned_at = datetime.now(UTC)
        account.plan_expires_at = None  # commercial plans don't expire unless canceled

        await self.db.flush()

        # Transactional email: welcome / subscription confirmed.
        # Best-effort (try/except) so a Brevo hiccup never breaks the webhook.
        await self._send_subscription_confirmed_email(account, sub, sub_obj)

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

    def _sync_plan_from_items(
        self, sub: "Subscription", sub_obj: dict
    ) -> bool:
        """Reconcile sub.plan / sub.billing_cycle with the Stripe items.

        Parses subscription.items.data and looks for an item whose price
        ID matches one of our commercial plan prices. If found and it
        differs from sub.plan, updates in place. Returns True if anything
        changed on the local row.
        """
        price_to_plan: dict[str, tuple[str, str]] = {}
        mapping = [
            (settings.stripe_price_solo_monthly, "solo", "monthly"),
            (settings.stripe_price_solo_yearly, "solo", "yearly"),
            (settings.stripe_price_equipe_monthly, "equipe", "monthly"),
            (settings.stripe_price_equipe_yearly, "equipe", "yearly"),
            (settings.stripe_price_groupe_monthly, "groupe", "monthly"),
            (settings.stripe_price_groupe_yearly, "groupe", "yearly"),
        ]
        for price_id, plan_code, cycle in mapping:
            if price_id:
                price_to_plan[price_id] = (plan_code, cycle)

        items = _get(sub_obj, "items") or {}
        items_data = _get(items, "data") or []
        for item in items_data:
            price = _get(item, "price") or {}
            price_id = _get(price, "id")
            if price_id and price_id in price_to_plan:
                new_plan, new_cycle = price_to_plan[price_id]
                if sub.plan != new_plan or sub.billing_cycle != new_cycle:
                    sub.plan = new_plan
                    sub.billing_cycle = new_cycle
                    return True
                return False
        return False

    async def _on_tax_id_changed(self, tax_id_obj: dict) -> None:
        """Log the tax_id update — the info lives on Stripe's Customer so we
        don't need to mirror it locally. Useful trail for B2B audits."""
        logger.info(
            "Stripe tax_id event for customer=%s type=%s value=%s",
            _get(tax_id_obj, "customer"),
            _get(tax_id_obj, "type"),
            _get(tax_id_obj, "value"),
        )

    async def _on_subscription_updated(self, sub_obj: dict) -> None:
        # Remember the plan before we mutate the local row — used to detect
        # downgrades initiated from the Stripe Customer Portal.
        previous_plan: str | None = None
        result0 = await self.db.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == sub_obj["id"]
            )
        )
        existing_for_plan_compare = result0.scalar_one_or_none()
        if existing_for_plan_compare is not None:
            previous_plan = existing_for_plan_compare.plan

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
        _start, _end = _sub_period(sub_obj)
        sub.current_period_start = _ts_to_dt(_start)
        sub.current_period_end = _ts_to_dt(_end)
        sub.cancel_at_period_end = bool(_get(sub_obj, "cancel_at_period_end"))
        canceled_at = _get(sub_obj, "canceled_at")
        if canceled_at:
            sub.canceled_at = _ts_to_dt(canceled_at)

        # Sync the primary plan from Stripe items. A client can switch
        # between Solo/Équipe/Groupe (or cycle monthly/yearly) via the
        # Customer Portal — Stripe sends us customer.subscription.updated
        # with the new price in items.data. We must reflect that locally
        # so the limits apply to the new plan. Add-on items (extra_user
        # etc.) are ignored here.
        plan_changed = self._sync_plan_from_items(sub, sub_obj)

        # Sync the Account status on known bad states
        account = await self.db.get(Account, sub.account_id)
        if account is None:
            return
        if sub_obj["status"] == "past_due":
            account.status = "past_due"
        elif sub_obj["status"] in ("active", "trialing"):
            account.status = "active"
        # Mirror the plan change on Account.
        if plan_changed:
            account.plan = sub.plan

        await self.db.flush()

        # Detect a downgrade initiated via Stripe Customer Portal: the
        # subscription has been changed to a plan with a smaller quota
        # than before. If the account already has more users/orgs/docs
        # than the new plan authorises, alert the owner by email so they
        # clean up before we do.
        _COMMERCIAL_ORDER = ["solo", "equipe", "groupe"]
        current_plan_after = sub.plan
        if (
            previous_plan is not None
            and previous_plan in _COMMERCIAL_ORDER
            and current_plan_after in _COMMERCIAL_ORDER
            and _COMMERCIAL_ORDER.index(current_plan_after)
                < _COMMERCIAL_ORDER.index(previous_plan)
        ):
            await self._notify_downgrade_overflow(account, previous_plan, current_plan_after)

    async def _notify_downgrade_overflow(
        self, account: Account, previous_plan: str, new_plan: str
    ) -> None:
        """Send an email if the post-downgrade state has more data than the new plan allows."""
        try:
            from app.services.plan_service import (
                PlanOverflowError,
                _validate_plan_fits_existing_data,
            )

            await _validate_plan_fits_existing_data(self.db, account.id, new_plan)
            return  # nothing to warn about
        except PlanOverflowError as exc:
            pass
        except Exception:
            logger.exception("downgrade overflow check failed for account %s", account.id)
            return

        try:
            from app.models.user import User as UserModel
            from app.services.email.sender import send_email

            owner = await self.db.get(UserModel, account.owner_id)
            if owner is None or not owner.is_active:
                return

            reasons_html = "".join(f"<li>{r}</li>" for r in exc.reasons)
            subject = "Downgrade AORIA RH — action requise"
            body = f"""
<p>Bonjour {owner.full_name},</p>
<p>Votre abonnement vient de passer de <strong>{previous_plan}</strong> à <strong>{new_plan}</strong>.
Votre compte contient actuellement plus d'éléments que ce que le plan <strong>{new_plan}</strong>
autorise&nbsp;:</p>
<ul>{reasons_html}</ul>
<p>La création de nouveaux éléments est désormais bloquée tant que vous n'êtes pas revenu
sous les limites. Merci de supprimer les éléments excédentaires sous 14 jours.</p>
<p>Si vous voulez garder l'existant, vous pouvez
<a href="{settings.frontend_url}/billing">remonter d'offre ici</a>.</p>
"""
            await send_email(owner.email, owner.full_name, subject, body)
        except Exception:
            logger.exception("downgrade overflow email failed for account %s", account.id)

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

        # Transactional email: confirmation of cancellation.
        if account is not None:
            await self._send_subscription_canceled_email(account, sub)

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

    async def _on_checkout_expired(self, session: dict) -> None:
        """Log-only: nothing to clean up on our side when a Stripe Checkout
        session times out. The Stripe Customer we may have created stays
        (it'll just sit idle). Useful trace for debugging conversion drops.
        """
        meta = _get(session, "metadata") or {}
        logger.info(
            "Stripe checkout expired for account=%s plan=%s",
            _get(meta, "account_id"),
            _get(meta, "plan"),
        )

    async def _on_charge_refunded(self, charge: dict) -> None:
        """A charge was fully or partially refunded.

        We only react to **full** refunds. Partial refunds are left to
        admin follow-up (they can come from bank disputes that will be
        reversed, or manual adjustments, etc.).
        """
        amount = int(_get(charge, "amount") or 0)
        amount_refunded = int(_get(charge, "amount_refunded") or 0)
        if amount == 0 or amount_refunded < amount:
            logger.info(
                "Partial refund ignored (charge=%s, %d/%d cents)",
                _get(charge, "id"), amount_refunded, amount,
            )
            return

        # Subscription refund → cancel immediately
        invoice_id = _get(charge, "invoice")
        if invoice_id:
            # Retrieve the invoice to get its subscription id
            try:
                inv = stripe.Invoice.retrieve(invoice_id)
                stripe_subscription_id = _get(inv, "subscription")
            except Exception:
                logger.exception("Could not retrieve invoice %s", invoice_id)
                stripe_subscription_id = None
            if stripe_subscription_id:
                result = await self.db.execute(
                    select(Subscription).where(
                        Subscription.stripe_subscription_id == stripe_subscription_id
                    )
                )
                sub = result.scalar_one_or_none()
                if sub is not None:
                    try:
                        stripe.Subscription.delete(stripe_subscription_id)
                    except Exception:
                        logger.exception(
                            "Stripe cancel failed for refunded sub %s (already canceled?)",
                            stripe_subscription_id,
                        )
                    sub.status = "canceled"
                    sub.canceled_at = datetime.now(UTC)
                    account = await self.db.get(Account, sub.account_id)
                    if account is not None:
                        account.status = "canceled"
                    await self.db.flush()
                    logger.info(
                        "Refunded subscription %s → canceled locally and on Stripe",
                        stripe_subscription_id,
                    )
                    return

        # One-shot booster refund → zero out remaining questions
        payment_intent_id = _get(charge, "payment_intent")
        if payment_intent_id:
            result = await self.db.execute(
                select(BoosterPurchase).where(
                    BoosterPurchase.stripe_payment_intent_id == payment_intent_id
                )
            )
            booster = result.scalar_one_or_none()
            if booster is not None:
                booster.questions_remaining = 0
                await self.db.flush()
                logger.info(
                    "Refunded booster %s → questions_remaining set to 0",
                    booster.id,
                )

    async def _send_subscription_confirmed_email(
        self,
        account: Account,
        sub: Subscription,
        sub_obj: dict,
    ) -> None:
        try:
            from app.models.user import User as UserModel
            from app.services.email.sender import send_email
            from app.services.email.templates import (
                render_subscription_confirmed_email,
            )

            owner = await self.db.get(UserModel, account.owner_id)
            if owner is None or not owner.is_active:
                return

            plan_label = _get_plan_label(sub.plan)

            next_date = (
                sub.current_period_end.strftime("%d/%m/%Y")
                if sub.current_period_end is not None
                else "—"
            )
            billing_url = f"{settings.frontend_url}/billing"

            # Try to attach the hosted invoice URL for the first payment.
            invoice_url: str | None = None
            latest_invoice_id = _get(sub_obj, "latest_invoice")
            if latest_invoice_id:
                try:
                    inv = stripe.Invoice.retrieve(latest_invoice_id)
                    invoice_url = _get(inv, "hosted_invoice_url")
                except Exception:
                    invoice_url = None

            subject, html = render_subscription_confirmed_email(
                full_name=owner.full_name,
                plan=sub.plan,
                plan_label=plan_label,
                cycle=sub.billing_cycle,
                next_billing_date=next_date,
                billing_url=billing_url,
                invoice_url=invoice_url,
            )
            await send_email(owner.email, owner.full_name, subject, html)
        except Exception:
            logger.exception(
                "subscription_confirmed email failed for account %s — swallowed",
                account.id,
            )

    async def _send_subscription_canceled_email(
        self, account: Account, sub: Subscription
    ) -> None:
        try:
            from app.models.user import User as UserModel
            from app.services.email.sender import send_email
            from app.services.email.templates import (
                render_subscription_canceled_email,
            )

            owner = await self.db.get(UserModel, account.owner_id)
            if owner is None or not owner.is_active:
                return

            plan_label = _get_plan_label(sub.plan)

            # The access usually remains until the end of the current
            # period — fall back on today if we somehow have no end date.
            end_date_dt = sub.current_period_end or datetime.now(UTC)
            end_date_label = end_date_dt.strftime("%d/%m/%Y")
            billing_url = f"{settings.frontend_url}/billing"

            subject, html = render_subscription_canceled_email(
                full_name=owner.full_name,
                plan_label=plan_label,
                end_date=end_date_label,
                billing_url=billing_url,
            )
            await send_email(owner.email, owner.full_name, subject, html)
        except Exception:
            logger.exception(
                "subscription_canceled email failed for account %s — swallowed",
                account.id,
            )

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
