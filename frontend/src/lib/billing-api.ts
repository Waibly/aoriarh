import { apiFetch } from "@/lib/api";

export type QuotaStatus = "ok" | "soft_warning" | "hard_warning" | "trial_expired" | "suspended";

export type AccountStatus = "active" | "trialing" | "past_due" | "suspended" | "canceled";

export type QuotaInfo = {
  plan: string;
  status: AccountStatus;
  used: number;
  quota: number;
  remaining: number;
  booster_remaining: number;
  period_start: string;
  period_end: string;
  quota_status: QuotaStatus;
  trial_ends_at: string | null;
};

export type SubscriptionInfo = {
  plan: string;
  billing_cycle: "monthly" | "yearly";
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
};

export type PlanCode = "solo" | "equipe" | "groupe";
export type BillingCycle = "monthly" | "yearly";

export type CheckoutResponse = {
  checkout_url: string;
  session_id: string;
};

export type PortalResponse = {
  portal_url: string;
};

export async function fetchQuota(token: string): Promise<QuotaInfo> {
  return apiFetch<QuotaInfo>("/billing/quota", { token });
}

export async function fetchSubscription(token: string): Promise<SubscriptionInfo | null> {
  return apiFetch<SubscriptionInfo | null>("/billing/subscription", { token });
}

export type DocsByOrg = {
  org_id: string;
  org_name: string;
  used: number;
  limit: number;
};

export type UsageSummary = {
  users: { used: number; limit: number };
  organisations: { used: number; limit: number };
  documents_by_org: DocsByOrg[];
  questions: {
    used: number;
    limit: number;
    booster_remaining: number;
    period_start: string;
    period_end: string;
    quota_status: QuotaStatus;
  };
};

export async function fetchUsageSummary(token: string): Promise<UsageSummary> {
  return apiFetch<UsageSummary>("/billing/usage-summary", { token });
}

export type AddonType = "extra_user" | "extra_org" | "extra_docs";

export type ActiveAddon = {
  id: string;
  addon_type: AddonType;
  quantity: number;
  unit_price_cents: number;
};

export async function fetchAddons(token: string): Promise<ActiveAddon[]> {
  return apiFetch<ActiveAddon[]>("/billing/addons", { token });
}

export async function addAddon(
  token: string,
  addon_type: AddonType,
): Promise<{ id: string; addon_type: AddonType; quantity: number }> {
  return apiFetch("/billing/addons", {
    token,
    method: "POST",
    body: JSON.stringify({ addon_type }),
  });
}

export async function removeAddon(token: string, addon_id: string): Promise<void> {
  return apiFetch(`/billing/addons/${addon_id}`, { token, method: "DELETE" });
}

export const ADDON_LABELS: Record<AddonType, string> = {
  extra_user: "Utilisateur additionnel",
  extra_org: "Organisation additionnelle",
  extra_docs: "Pack +500 documents",
};

export async function startCheckout(
  token: string,
  plan: PlanCode,
  cycle: BillingCycle,
): Promise<CheckoutResponse> {
  return apiFetch<CheckoutResponse>("/billing/checkout", {
    token,
    method: "POST",
    body: JSON.stringify({ plan, cycle }),
  });
}

export async function startBoosterCheckout(token: string): Promise<CheckoutResponse> {
  return apiFetch<CheckoutResponse>("/billing/booster/checkout", {
    token,
    method: "POST",
  });
}

export async function openCustomerPortal(token: string): Promise<PortalResponse> {
  return apiFetch<PortalResponse>("/billing/portal", {
    token,
    method: "POST",
  });
}

export async function changePlan(
  token: string,
  plan: PlanCode,
  cycle: BillingCycle,
): Promise<{ plan: string; cycle: string; stripe_subscription_id: string }> {
  return apiFetch("/billing/change-plan", {
    token,
    method: "POST",
    body: JSON.stringify({ plan, cycle }),
  });
}

// Local catalogue — kept in sync with backend/app/core/plans.py.
// Used to render the pricing page without an extra round-trip.
export const PLANS_CATALOG = {
  solo: {
    name: "Solo",
    target: "Dirigeant TPE, PME 1 RH, petit CSE",
    priceMonthly: 79,
    priceYearly: 790,
    features: [
      "1 utilisateur (jusqu'à 3 add-ons)",
      "1 organisation",
      "100 documents / organisation",
      "1 convention collective",
      "300 questions / mois",
      "Chat in-app",
    ],
  },
  equipe: {
    name: "Équipe",
    target: "PME équipe RH, CSE moyen, DRH",
    priceMonthly: 149,
    priceYearly: 1490,
    featured: true,
    features: [
      "5 utilisateurs (jusqu'à 3 add-ons)",
      "3 organisations",
      "300 documents / organisation",
      "5 conventions collectives",
      "900 questions / mois",
      "Chat in-app",
    ],
  },
  groupe: {
    name: "Groupe",
    target: "DRH multi-entités, CSE central, ETI",
    priceMonthly: 279,
    priceYearly: 2790,
    features: [
      "10 utilisateurs (jusqu'à 3 add-ons)",
      "10 organisations",
      "1 000 documents / organisation",
      "Conventions collectives illimitées",
      "2 400 questions / mois",
      "Chat in-app + onboarding personnalisé",
    ],
  },
} as const;

export const PLAN_LABELS: Record<string, string> = {
  gratuit: "Essai gratuit",
  invite: "Invité",
  vip: "VIP",
  solo: "Solo",
  equipe: "Équipe",
  groupe: "Groupe",
};
