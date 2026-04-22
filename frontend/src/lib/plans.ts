/**
 * Unique source of truth for plan metadata on the frontend.
 *
 * Mirrors the backend constants in `app/core/plans.py`. Every piece of UI
 * that needs plan labels, features, pricing or badge styling imports from
 * here — never duplicates the list.
 *
 * When updating: also update `backend/app/core/plans.py` so the two stay
 * consistent. The backend enforces limits; the frontend only shows them.
 */

/** Commercial plans (sold via Stripe). */
export type PlanCode = "solo" | "equipe" | "groupe";

/** Any plan code including technical (non-sold) plans. */
export type AnyPlanCode = PlanCode | "gratuit" | "invite" | "vip";

export type BillingCycle = "monthly" | "yearly";

export interface PlanMeta {
  code: AnyPlanCode;
  label: string;
  /** Short tagline shown on pricing cards / admin column. */
  target: string;
  /** Monthly price in €. Null for technical (non-sold) plans. */
  priceMonthly: number | null;
  /** Yearly price in € (upfront). Null for technical plans. */
  priceYearly: number | null;
  /** Plan highlighted on the public pricing page. */
  featured?: boolean;
  /** True for Solo/Équipe/Groupe (sold via Stripe). */
  commercial: boolean;
  /** Tailwind classes for the badge variant on admin tables. */
  badgeClassName: string;
  features: string[];
}

export const PLANS: Record<AnyPlanCode, PlanMeta> = {
  gratuit: {
    code: "gratuit",
    label: "Essai",
    target: "14 jours pour tester avant d'acheter",
    priceMonthly: null,
    priceYearly: null,
    commercial: false,
    badgeClassName: "",
    features: [
      "Accès complet pendant 14 jours",
      "1 utilisateur, 1 organisation, 1 convention collective",
      "100 documents",
      "300 questions sur la période d'essai",
    ],
  },
  invite: {
    code: "invite",
    label: "Invité",
    target: "Accès gratuit accordé manuellement",
    priceMonthly: null,
    priceYearly: null,
    commercial: false,
    badgeClassName: "border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0]",
    features: [
      "5 utilisateurs, 3 organisations",
      "300 documents par organisation",
      "5 conventions collectives",
      "900 questions / mois",
    ],
  },
  vip: {
    code: "vip",
    label: "VIP",
    target: "Accès VIP accordé par l'équipe",
    priceMonthly: null,
    priceYearly: null,
    commercial: false,
    badgeClassName: "border-amber-500 bg-amber-500/10 text-amber-600",
    features: [
      "5 utilisateurs, 3 organisations",
      "300 documents par organisation",
      "5 conventions collectives",
      "900 questions / mois",
    ],
  },
  solo: {
    code: "solo",
    label: "Solo",
    target: "Dirigeant TPE, PME 1 RH, petit CSE",
    priceMonthly: 79,
    priceYearly: 790,
    commercial: true,
    badgeClassName: "border-primary bg-primary/10 text-primary",
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
    code: "equipe",
    label: "Équipe",
    target: "PME équipe RH, CSE moyen, DRH",
    priceMonthly: 149,
    priceYearly: 1490,
    featured: true,
    commercial: true,
    badgeClassName: "border-primary bg-primary/15 text-primary font-medium",
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
    code: "groupe",
    label: "Groupe",
    target: "DRH multi-entités, CSE central, ETI",
    priceMonthly: 279,
    priceYearly: 2790,
    commercial: true,
    badgeClassName: "border-primary bg-primary/20 text-primary font-semibold",
    features: [
      "10 utilisateurs (jusqu'à 3 add-ons)",
      "10 organisations",
      "1 000 documents / organisation",
      "Conventions collectives illimitées",
      "2 400 questions / mois",
      "Chat in-app + onboarding personnalisé",
    ],
  },
};

/** Human-readable label with safe fallback on unknown plans. */
export function getPlanLabel(code: string): string {
  return (code in PLANS ? PLANS[code as AnyPlanCode].label : code) || code;
}

export function isCommercialPlan(code: string): boolean {
  return code in PLANS ? PLANS[code as AnyPlanCode].commercial : false;
}

/** Commercial plans (sold on the pricing page), in display order. */
export const COMMERCIAL_PLANS: readonly PlanCode[] = [
  "solo",
  "equipe",
  "groupe",
] as const;
