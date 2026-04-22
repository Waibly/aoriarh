"""Plan and limits configuration for AORIA RH.

Source of truth for plan limits, prices and add-on pricing.
Kept in Python rather than in a DB table because plans evolve slowly
and must be versioned in git alongside the code that enforces them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanLimits:
    """Limits enforced for a given plan."""

    users_included: int
    orgs_included: int
    docs_per_org: int
    ccn_per_org: int | None  # None = unlimited
    questions_per_month: int
    max_extra_users: int = 0  # only meaningful for commercial plans


# --- Plan limits -----------------------------------------------------------

# Technical plans (not sold, assigned manually by admins)
# gratuit = trial plan (14 days). Aligné sur les limites Solo pour que
# l'utilisateur puisse tester le produit dans des conditions réalistes,
# tout en gardant un périmètre réduit (1 user / 1 org).
LIMITS_GRATUIT = PlanLimits(
    users_included=1,
    orgs_included=1,
    docs_per_org=100,
    ccn_per_org=1,
    questions_per_month=300,
)

LIMITS_INVITE = PlanLimits(
    users_included=5,
    orgs_included=3,
    docs_per_org=300,
    ccn_per_org=5,
    questions_per_month=900,
)

LIMITS_VIP = PlanLimits(
    users_included=5,
    orgs_included=3,
    docs_per_org=300,
    ccn_per_org=5,
    questions_per_month=900,
)

# Commercial plans (Stripe)
LIMITS_SOLO = PlanLimits(
    users_included=1,
    max_extra_users=3,
    orgs_included=1,
    docs_per_org=100,
    ccn_per_org=1,
    questions_per_month=300,
)

LIMITS_EQUIPE = PlanLimits(
    users_included=5,
    max_extra_users=3,
    orgs_included=3,
    docs_per_org=300,
    ccn_per_org=5,
    questions_per_month=900,
)

LIMITS_GROUPE = PlanLimits(
    users_included=10,
    max_extra_users=3,
    orgs_included=10,
    docs_per_org=1000,
    ccn_per_org=None,
    questions_per_month=2400,
)


PLAN_LIMITS: dict[str, PlanLimits] = {
    "gratuit": LIMITS_GRATUIT,
    "invite": LIMITS_INVITE,
    "vip": LIMITS_VIP,
    "solo": LIMITS_SOLO,
    "equipe": LIMITS_EQUIPE,
    "groupe": LIMITS_GROUPE,
}


TECHNICAL_PLANS: frozenset[str] = frozenset({"gratuit", "invite", "vip"})
COMMERCIAL_PLANS: frozenset[str] = frozenset({"solo", "equipe", "groupe"})
ALL_PLANS: frozenset[str] = TECHNICAL_PLANS | COMMERCIAL_PLANS


# --- Display metadata (single source of truth) -----------------------------
# Every human-readable plan label and feature list for the product lives here.
# Other modules (billing_service, stripe_service, email/templates, admin API)
# import from this file — do NOT re-define plan labels elsewhere.

PLAN_LABELS: dict[str, str] = {
    "gratuit": "Essai",
    "invite": "Invité",
    "vip": "VIP",
    "solo": "Solo",
    "equipe": "Équipe",
    "groupe": "Groupe",
}

PLAN_FEATURES: dict[str, list[str]] = {
    "gratuit": [
        "Accès complet pendant 14 jours",
        "1 utilisateur, 1 organisation, 1 convention collective",
        "100 documents",
        "300 questions sur la période d'essai",
    ],
    "invite": [
        "5 utilisateurs, 3 organisations",
        "300 documents par organisation",
        "5 conventions collectives",
        "900 questions / mois",
    ],
    "vip": [
        "5 utilisateurs, 3 organisations",
        "300 documents par organisation",
        "5 conventions collectives",
        "900 questions / mois",
    ],
    "solo": [
        "1 utilisateur (jusqu'à 3 utilisateurs additionnels via add-on)",
        "1 organisation",
        "100 documents par organisation",
        "1 convention collective installable",
        "300 questions juridiques RH / mois",
        "Chat in-app avec réponses sourcées",
    ],
    "equipe": [
        "5 utilisateurs inclus (jusqu'à 3 utilisateurs additionnels via add-on)",
        "3 organisations",
        "300 documents par organisation",
        "5 conventions collectives installables",
        "900 questions juridiques RH / mois",
        "Chat in-app avec réponses sourcées",
    ],
    "groupe": [
        "10 utilisateurs inclus (jusqu'à 3 utilisateurs additionnels via add-on)",
        "10 organisations",
        "1 000 documents par organisation",
        "Conventions collectives illimitées",
        "2 400 questions juridiques RH / mois",
        "Chat in-app + onboarding personnalisé",
    ],
}


def get_label(plan: str) -> str:
    """Return the human-readable label for a plan code (fallback = raw code)."""
    return PLAN_LABELS.get(plan, plan)


# --- Prices (in cents) -----------------------------------------------------

PRICE_MONTHLY_CENTS: dict[str, int] = {
    "solo": 7900,
    "equipe": 14900,
    "groupe": 27900,
}

PRICE_YEARLY_CENTS: dict[str, int] = {
    "solo": 79000,
    "equipe": 149000,
    "groupe": 279000,
}

ADDON_PRICES_CENTS: dict[str, int] = {
    "extra_user": 1500,   # +1 user / month
    "extra_org": 1900,    # +1 organisation / month
    "extra_docs": 1000,   # +500 documents / month
}

BOOSTER_PRICE_CENTS: int = 2500      # one-shot purchase
BOOSTER_QUESTIONS: int = 500         # questions granted per booster


# --- Trial and lifecycle ---------------------------------------------------

TRIAL_DURATION_DAYS: int = 14
GRACE_AFTER_CANCEL_DAYS: int = 30       # retention after voluntary cancellation
GRACE_AFTER_UNPAID_DAYS: int = 60       # retention after payment suspension
GRACE_AFTER_TRIAL_END_DAYS: int = 30    # retention after unconverted trial


def get_limits(plan: str) -> PlanLimits:
    """Return the PlanLimits for a given plan code."""
    if plan not in PLAN_LIMITS:
        raise ValueError(f"Unknown plan: {plan!r}")
    return PLAN_LIMITS[plan]


def is_commercial(plan: str) -> bool:
    return plan in COMMERCIAL_PLANS


def is_technical(plan: str) -> bool:
    return plan in TECHNICAL_PLANS
