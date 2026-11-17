"""Tax routing for professional SaaS customers, before Stripe Checkout.

The billing establishment determines the route; a user's IP address does not.
Keep no-tax territories distinct from a taxable transaction at a zero rate.
"""

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class BillingTaxPolicy:
    territory: str
    mode: str  # automatic | dom_vat | no_tax
    invoice_mention: str = ""


TERRITORY_PREFIXES = (
    ("97133", "BL"),
    ("97150", "MF"),
    ("971", "GP"),
    ("972", "MQ"),
    ("973", "GF"),
    ("974", "RE"),
    ("975", "PM"),
    ("976", "YT"),
    ("986", "WF"),
    ("987", "PF"),
    ("988", "NC"),
)
FRENCH_TERRITORIES = {territory for _, territory in TERRITORY_PREFIXES}
BLOCKED_TERRITORIES = {"MF": "Saint-Martin", "PF": "Polynésie française"}


def billing_tax_policy(country: str, postal_code: str) -> BillingTaxPolicy:
    country = country.strip().upper()
    postal_code = postal_code.strip()
    postal_territory = (
        next(
            (
                territory
                for prefix, territory in TERRITORY_PREFIXES
                if postal_code.startswith(prefix)
            ),
            None,
        )
        if len(postal_code) == 5 and postal_code.isascii() and postal_code.isdigit()
        else None
    )
    territory = country
    if country == "FR" or country in FRENCH_TERRITORIES:
        # A French postal address is often entered as FR even in a territory.
        territory = postal_territory or country
        if territory in BLOCKED_TERRITORIES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Les souscriptions ne sont pas disponibles pour les entreprises établies en "
                    f"{BLOCKED_TERRITORIES[territory]}."
                ),
            )
        if len(postal_code) != 5 or not postal_code.isascii() or not postal_code.isdigit():
            raise HTTPException(
                status_code=422, detail="Renseignez un code postal à cinq chiffres."
            )
        if country != "FR" and postal_territory != country:
            raise HTTPException(
                status_code=422,
                detail="Le code postal ne correspond pas au territoire de facturation sélectionné.",
            )
    if territory in {"RE", "GP", "MQ"}:
        return BillingTaxPolicy(territory, "dom_vat")
    if territory in {"GF", "YT"}:
        return BillingTaxPolicy(territory, "no_tax", "TVA non applicable — article 294 du CGI.")
    if territory == "NC":
        return BillingTaxPolicy(
            territory,
            "no_tax",
            "TVA non applicable — article 259, 1° du CGI. "
            "TGC : autoliquidation par le preneur professionnel (article Lp. 507 du code local).",
        )
    if territory in {"BL", "PM", "WF"}:
        return BillingTaxPolicy(territory, "no_tax", "TVA non applicable — article 259, 1° du CGI.")
    return BillingTaxPolicy(territory, "automatic")
