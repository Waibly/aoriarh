/**
 * Sanity tests for the plan catalog. Ensure the centralisation stays correct:
 * - every PlanCode and AnyPlanCode has a PlanMeta
 * - commercial plans have prices, technical ones don't
 * - getPlanLabel returns the raw code on unknown inputs
 */

import {
  PLANS,
  COMMERCIAL_PLANS,
  getPlanLabel,
  isCommercialPlan,
  type AnyPlanCode,
} from "./plans";

describe("PLANS catalog", () => {
  const ALL_CODES: AnyPlanCode[] = [
    "gratuit",
    "invite",
    "vip",
    "solo",
    "equipe",
    "groupe",
  ];

  it("has metadata for every plan code", () => {
    for (const code of ALL_CODES) {
      expect(PLANS[code]).toBeDefined();
      expect(PLANS[code].label).toBeTruthy();
      expect(PLANS[code].features.length).toBeGreaterThan(0);
      expect(PLANS[code].target).toBeTruthy();
    }
  });

  it("marks commercial plans with prices", () => {
    for (const code of COMMERCIAL_PLANS) {
      expect(PLANS[code].commercial).toBe(true);
      expect(PLANS[code].priceMonthly).toBeGreaterThan(0);
      expect(PLANS[code].priceYearly).toBeGreaterThan(0);
    }
  });

  it("leaves technical plans without prices", () => {
    for (const code of ["gratuit", "invite", "vip"] as const) {
      expect(PLANS[code].commercial).toBe(false);
      expect(PLANS[code].priceMonthly).toBeNull();
      expect(PLANS[code].priceYearly).toBeNull();
    }
  });

  it("getPlanLabel falls back to the raw code when unknown", () => {
    expect(getPlanLabel("solo")).toBe("Solo");
    expect(getPlanLabel("equipe")).toBe("Équipe");
    expect(getPlanLabel("gratuit")).toBe("Essai");
    expect(getPlanLabel("unknown-plan")).toBe("unknown-plan");
    expect(getPlanLabel("")).toBe("");
  });

  it("isCommercialPlan correctly classifies plan codes", () => {
    expect(isCommercialPlan("solo")).toBe(true);
    expect(isCommercialPlan("equipe")).toBe(true);
    expect(isCommercialPlan("groupe")).toBe(true);
    expect(isCommercialPlan("gratuit")).toBe(false);
    expect(isCommercialPlan("invite")).toBe(false);
    expect(isCommercialPlan("vip")).toBe(false);
    expect(isCommercialPlan("unknown")).toBe(false);
  });
});
