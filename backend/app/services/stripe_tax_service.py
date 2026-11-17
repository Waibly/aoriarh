"""Billing coordinates and explicit tax rates for unsupported Stripe Tax territories."""

import stripe
from fastapi import HTTPException

from app.schemas.stripe_billing import BillingProfile
from app.services.billing_tax import BillingTaxPolicy, billing_tax_policy


def get(obj, key, default=None):
    return obj[key] if obj is not None and key in obj else default


def profile_from_customer(customer) -> BillingProfile | None:
    address = get(customer, "address") or {}
    fields = {
        key: get(address, key) or "" for key in ("line1", "line2", "postal_code", "city", "country")
    }
    if not all(fields[key] for key in ("line1", "postal_code", "city", "country")):
        return None
    name = get(customer, "name") or ""
    if not name:
        return None
    return BillingProfile(
        business_name=name,
        professional=get(get(customer, "metadata"), "aoria_professional") == "true",
        **fields,
    )


def require_profile(customer) -> tuple[BillingProfile, BillingTaxPolicy]:
    profile = profile_from_customer(customer)
    if profile is None or not profile.professional:
        raise HTTPException(
            status_code=409,
            detail="Complétez les coordonnées de votre entreprise avant le paiement.",
        )
    return profile, billing_tax_policy(profile.country, profile.postal_code)


def dom_vat_rate_id() -> str:
    for rate in stripe.TaxRate.list(active=True, limit=100).auto_paging_iter():
        if (
            get(get(rate, "metadata"), "aoria_tax") == "dom_vat_8_5"
            and float(get(rate, "percentage", 0)) == 8.5
            and get(rate, "inclusive") is False
        ):
            return rate["id"]
    rate = stripe.TaxRate.create(
        display_name="TVA",
        description="TVA Réunion, Guadeloupe, Martinique — services professionnels",
        jurisdiction="Réunion, Guadeloupe, Martinique",
        country="FR",
        percentage=8.5,
        inclusive=False,
        metadata={"aoria_tax": "dom_vat_8_5"},
        idempotency_key="aoria-dom-vat-8-5-exclusive-v1",
    )
    return rate["id"]


def checkout_tax_params(policy: BillingTaxPolicy) -> dict:
    if policy.mode == "automatic":
        return {"automatic_tax": {"enabled": True}}
    params = {"automatic_tax": {"enabled": False}}
    if policy.mode == "dom_vat":
        params["tax_rates"] = [dom_vat_rate_id()]
    return params


def subscription_tax_params(policy: BillingTaxPolicy) -> dict:
    params = checkout_tax_params(policy)
    rates = params.pop("tax_rates", [])
    return {**params, "default_tax_rates": rates}
