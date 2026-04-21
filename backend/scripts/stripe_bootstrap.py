"""Bootstrap Stripe products and prices for AORIA RH.

Creates (or retrieves, if already created by a previous run) the full set
of products and recurring/one-shot prices used by the commercial offer:

  - 3 subscription plans × 2 billing cycles  = 6 recurring prices
  - 3 monthly add-on prices (extra_user, extra_org, extra_docs)
  - 1 one-shot price (booster +500 questions)

The script is idempotent: it uses metadata.aoria_code to match existing
products/prices, so running it twice is safe. It never archives or
mutates an existing price — if an amount has changed on Stripe's side,
the script prints a warning and keeps the old price.

Run with:
    docker compose exec backend python scripts/stripe_bootstrap.py

After completion, copy the printed block into your .env file.
"""

from __future__ import annotations

import sys

import stripe

from app.core.config import settings
from app.core.plans import (
    ADDON_PRICES_CENTS,
    BOOSTER_PRICE_CENTS,
    PRICE_MONTHLY_CENTS,
    PRICE_YEARLY_CENTS,
)


# --- Product catalogue ------------------------------------------------------


PRODUCTS: list[dict] = [
    {
        "aoria_code": "solo",
        "name": "AORIA RH — Solo",
        "description": "Plan Solo · 1 utilisateur · 1 organisation · 300 questions / mois",
        "prices": [
            {
                "aoria_code": "solo_monthly",
                "amount": PRICE_MONTHLY_CENTS["solo"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_SOLO_MONTHLY",
            },
            {
                "aoria_code": "solo_yearly",
                "amount": PRICE_YEARLY_CENTS["solo"],
                "interval": "year",
                "env_var": "STRIPE_PRICE_SOLO_YEARLY",
            },
        ],
    },
    {
        "aoria_code": "equipe",
        "name": "AORIA RH — Équipe",
        "description": "Plan Équipe · 5 utilisateurs · 3 organisations · 900 questions / mois",
        "prices": [
            {
                "aoria_code": "equipe_monthly",
                "amount": PRICE_MONTHLY_CENTS["equipe"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_EQUIPE_MONTHLY",
            },
            {
                "aoria_code": "equipe_yearly",
                "amount": PRICE_YEARLY_CENTS["equipe"],
                "interval": "year",
                "env_var": "STRIPE_PRICE_EQUIPE_YEARLY",
            },
        ],
    },
    {
        "aoria_code": "groupe",
        "name": "AORIA RH — Groupe",
        "description": "Plan Groupe · 10 utilisateurs · 10 organisations · 2 400 questions / mois · onboarding inclus",
        "prices": [
            {
                "aoria_code": "groupe_monthly",
                "amount": PRICE_MONTHLY_CENTS["groupe"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_GROUPE_MONTHLY",
            },
            {
                "aoria_code": "groupe_yearly",
                "amount": PRICE_YEARLY_CENTS["groupe"],
                "interval": "year",
                "env_var": "STRIPE_PRICE_GROUPE_YEARLY",
            },
        ],
    },
    {
        "aoria_code": "addon_user",
        "name": "AORIA RH — Utilisateur additionnel",
        "description": "Add-on : +1 utilisateur (accès partagé au quota du plan, maximum 3 add-ons par abonnement)",
        "prices": [
            {
                "aoria_code": "addon_user_monthly",
                "amount": ADDON_PRICES_CENTS["extra_user"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_ADDON_USER",
            },
        ],
    },
    {
        "aoria_code": "addon_org",
        "name": "AORIA RH — Organisation additionnelle",
        "description": "Add-on : +1 organisation (espace de travail supplémentaire)",
        "prices": [
            {
                "aoria_code": "addon_org_monthly",
                "amount": ADDON_PRICES_CENTS["extra_org"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_ADDON_ORG",
            },
        ],
    },
    {
        "aoria_code": "addon_docs",
        "name": "AORIA RH — +500 documents",
        "description": "Add-on : +500 documents par organisation",
        "prices": [
            {
                "aoria_code": "addon_docs_monthly",
                "amount": ADDON_PRICES_CENTS["extra_docs"],
                "interval": "month",
                "env_var": "STRIPE_PRICE_ADDON_DOCS",
            },
        ],
    },
    {
        "aoria_code": "booster",
        "name": "AORIA RH — Pack booster +500 questions",
        "description": "Pack ponctuel de +500 questions. Valable jusqu'à la fin du cycle en cours.",
        "prices": [
            {
                "aoria_code": "booster_oneshot",
                "amount": BOOSTER_PRICE_CENTS,
                "interval": None,  # one-shot payment
                "env_var": "STRIPE_PRICE_BOOSTER",
            },
        ],
    },
]


# --- Helpers ----------------------------------------------------------------


def _search_product(aoria_code: str):
    results = stripe.Product.search(query=f"metadata['aoria_code']:'{aoria_code}' AND active:'true'")
    return results.data[0] if results.data else None


def _search_price(aoria_code: str):
    results = stripe.Price.search(query=f"metadata['aoria_code']:'{aoria_code}' AND active:'true'")
    return results.data[0] if results.data else None


def find_or_create_product(aoria_code: str, name: str, description: str):
    existing = _search_product(aoria_code)
    if existing is not None:
        print(f"  ✓ Product exists: {name} ({existing['id']})")
        return existing
    product = stripe.Product.create(
        name=name,
        description=description,
        metadata={"aoria_code": aoria_code},
    )
    print(f"  + Product created: {name} ({product['id']})")
    return product


def find_or_create_price(product_id: str, price_cfg: dict):
    aoria_code = price_cfg["aoria_code"]
    amount = price_cfg["amount"]
    interval = price_cfg["interval"]

    existing = _search_price(aoria_code)
    if existing is not None:
        if existing["unit_amount"] != amount:
            print(
                f"  ! Price {aoria_code} exists on Stripe with a different amount "
                f"({existing['unit_amount']} cents vs expected {amount}). "
                f"Keeping the existing one: {existing['id']}. "
                f"To change the price, archive it in the dashboard and re-run."
            )
        else:
            print(f"  ✓ Price exists: {aoria_code} ({existing['id']})")
        return existing

    params: dict = {
        "product": product_id,
        "unit_amount": amount,
        "currency": "eur",
        "tax_behavior": "exclusive",  # prices are HT (VAT added by Stripe Tax if enabled)
        "metadata": {"aoria_code": aoria_code},
    }
    if interval is not None:
        params["recurring"] = {"interval": interval, "interval_count": 1}

    price = stripe.Price.create(**params)
    kind = f"{interval}ly" if interval else "one-shot"
    print(f"  + Price created: {aoria_code} ({kind}, {amount / 100:.2f} €) → {price['id']}")
    return price


# --- Main -------------------------------------------------------------------


def main() -> int:
    if not settings.stripe_secret_key:
        print("ERROR: STRIPE_SECRET_KEY is not set in .env", file=sys.stderr)
        return 1
    stripe.api_key = settings.stripe_secret_key

    # Tell the user which mode we're running in.
    account = stripe.Account.retrieve()
    mode = "LIVE" if settings.stripe_secret_key.startswith("sk_live_") else "TEST"
    print(f"Stripe account: {account['id']} — mode {mode}")
    print("-" * 70)

    env_lines: list[str] = []

    for product_cfg in PRODUCTS:
        print(f"\n[{product_cfg['aoria_code']}]")
        product = find_or_create_product(
            aoria_code=product_cfg["aoria_code"],
            name=product_cfg["name"],
            description=product_cfg["description"],
        )
        for price_cfg in product_cfg["prices"]:
            price = find_or_create_price(product["id"], price_cfg)
            env_lines.append(f"{price_cfg['env_var']}={price['id']}")

    print("\n" + "=" * 70)
    print("COPY THE BLOCK BELOW INTO YOUR .env FILE:")
    print("=" * 70)
    print()
    for line in env_lines:
        print(line)
    print()
    print("=" * 70)
    print(
        "\nNext steps:\n"
        "  1. Paste the block above into your .env\n"
        "  2. Configure the webhook endpoint in the Stripe dashboard:\n"
        "     URL    → https://api.aoriarh.fr/api/v1/billing/webhook\n"
        "     Events → checkout.session.completed,\n"
        "              customer.subscription.created,\n"
        "              customer.subscription.updated,\n"
        "              customer.subscription.deleted,\n"
        "              invoice.paid,\n"
        "              invoice.payment_failed\n"
        "     Copy the signing secret → STRIPE_WEBHOOK_SECRET in .env\n"
        "  3. Restart the backend: docker compose up -d --build backend\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
