import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { signOut } from "next-auth/react";
import { apiFetch, authFetch } from "@/lib/api";
import * as billing from "@/lib/billing-api";
import BillingPage from "@/app/(dashboard)/billing/page";
import AccountPage from "@/app/(dashboard)/account/page";
import { TrialBanner } from "@/components/trial-banner";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { access_token: "test-token" }, update: jest.fn() }),
  signOut: jest.fn(),
}));
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn(), authFetch: jest.fn() }));
jest.mock("@/lib/billing-api");
jest.mock("@/lib/org-context", () => ({
  // The selected organisation can belong to somebody else even when the
  // authenticated user owns the personal account managed by /billing.
  useOrg: () => ({ workspaceName: "Invited workspace", isWorkspaceOwner: false }),
}));
jest.mock("@/lib/incidents", () => ({ reportIncident: jest.fn() }));

beforeEach(() => {
  jest.clearAllMocks();
  (apiFetch as jest.Mock).mockResolvedValue({
    id: "user", full_name: "Member", email: "member@test.com", role: "user",
    is_workspace_owner: false,
  });
  jest.mocked(billing.fetchQuota).mockResolvedValue({
    plan: "equipe", status: "active", used: 1100, quota: 900, remaining: 0,
    booster_remaining: 0, quota_status: "hard_warning", trial_ends_at: null,
    period_start: "2026-11-01", period_end: "2026-12-01",
  });
  jest.mocked(billing.fetchSubscription).mockResolvedValue({
    plan: "equipe", status: "active", billing_cycle: "monthly",
    current_period_end: "2026-12-01", cancel_at_period_end: false,
  });
  jest.mocked(billing.fetchUsageSummary).mockResolvedValue({
    users: { used: 2, limit: 5 }, organisations: { used: 1, limit: 3 },
    documents_by_org: [],
    questions: {
      used: 1100, limit: 900, booster_remaining: 0, quota_status: "hard_warning",
      period_start: "2026-11-01", period_end: "2026-12-01",
    },
  });
  jest.mocked(billing.fetchAddons).mockResolvedValue([]);
  jest.mocked(billing.fetchInvoices).mockResolvedValue([]);
});

it("keeps shared consumption visible and hides every billing action for an invited member", async () => {
  render(<BillingPage />);
  expect(await screen.findByText("Questions ce mois-ci")).toBeInTheDocument();
  expect(screen.getByText(/Seul le propriétaire peut gérer/)).toBeInTheDocument();
  for (const name of [/Résilier/, /Portail Stripe/, /Modifier ma carte/, /Acheter/, /Souscrire/]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
  expect(screen.queryByText("Nos offres")).not.toBeInTheDocument();
  expect(billing.fetchInvoices).not.toHaveBeenCalled();
});

it("allows the personal account owner to cancel even with another organisation selected", async () => {
  (apiFetch as jest.Mock).mockResolvedValue({ is_workspace_owner: true });
  jest.mocked(billing.cancelSubscription).mockResolvedValue({
    plan: "equipe", cycle: "monthly", stripe_subscription_id: "sub_test",
  });
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(true);
  try {
    render(<BillingPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Résilier" }));
    await waitFor(() => expect(billing.cancelSubscription).toHaveBeenCalledWith("test-token"));
    expect(apiFetch).toHaveBeenCalledWith("/users/me", { token: "test-token" });
    expect(billing.fetchInvoices).toHaveBeenCalledWith("test-token");
  } finally {
    confirm.mockRestore();
  }
});

it("keeps subscription offers available to the owner after the trial expires", async () => {
  (apiFetch as jest.Mock).mockResolvedValue({ is_workspace_owner: true });
  jest.mocked(billing.fetchQuota).mockRejectedValue(new Error("Essai expiré"));
  render(<BillingPage />);
  expect(await screen.findByText("Nos offres")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Souscrire Solo" })).toBeEnabled();
});

it("does not offer booster checkout to an invited member from the quota banner", async () => {
  render(<TrialBanner />);
  expect(await screen.findByText(/Contactez le propriétaire pour adapter/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Acheter/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Gérer mon abonnement" })).not.toBeInTheDocument();
});

it("keeps the account deletion dialog open and shows the Stripe failure without signing out", async () => {
  (apiFetch as jest.Mock).mockResolvedValue({
    id: "owner", full_name: "Owner", email: "owner@test.com", role: "manager",
    is_workspace_owner: true,
  });
  (authFetch as jest.Mock).mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Stripe indisponible. Votre compte n'a pas été supprimé." }),
  });
  render(<AccountPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Supprimer mon compte" }));
  expect(screen.getByText(/Votre abonnement payant sera résilié immédiatement/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/Tapez/), { target: { value: "SUPPRIMER MON COMPTE" } });
  fireEvent.click(screen.getByRole("button", { name: "Supprimer définitivement" }));
  expect(await screen.findByText(/Stripe indisponible/)).toBeInTheDocument();
  expect(signOut).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Supprimer définitivement" })).toBeEnabled();
});
