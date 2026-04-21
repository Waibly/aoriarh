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
