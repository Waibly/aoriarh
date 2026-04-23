import { apiFetch } from "@/lib/api";
import type { BillingCycle, PlanCode } from "@/lib/plans";

// Re-export the plan types so consumers can keep importing from billing-api
// if they want. New code should import directly from `@/lib/plans`.
export type { BillingCycle, PlanCode } from "@/lib/plans";

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

export type ChangePlanPreview = {
  amount_due_cents: number;
  amount_due_eur: number;
  amount_tax_cents: number;
  amount_subtotal_cents: number;
  currency: string;
  next_billing_at: string | null;
};

export async function previewChangePlan(
  token: string,
  plan: PlanCode,
  cycle: BillingCycle,
): Promise<ChangePlanPreview> {
  return apiFetch<ChangePlanPreview>("/billing/preview-change-plan", {
    token,
    method: "POST",
    body: JSON.stringify({ plan, cycle }),
  });
}

export async function reactivateSubscription(
  token: string,
): Promise<{ plan: string; cycle: string; stripe_subscription_id: string }> {
  return apiFetch("/billing/reactivate", {
    token,
    method: "POST",
  });
}

// NOTE: plan metadata (labels, features, pricing) lives in `@/lib/plans`.
// Import PLANS / getPlanLabel / COMMERCIAL_PLANS from there directly.
// Imports added below re-export names for backwards compat while callers
// migrate — the aliases point to the central source, nothing is duplicated.
export { PLANS, getPlanLabel, COMMERCIAL_PLANS } from "@/lib/plans";
