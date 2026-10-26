import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { EmailingSetup } from "@/components/admin/emailing/setup";
import { EmailingStats } from "@/components/admin/emailing/stats";
import CampaignsPanel from "@/components/admin/emailing/campaigns-panel";
import { apiFetch } from "@/lib/api";
import type {
  CampaignStats,
  EmailCampaign,
} from "@/components/admin/emailing/types";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { access_token: "test-token" } }),
}));
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
jest.mock("@/lib/toast", () => ({
  toast: { error: jest.fn(), success: jest.fn() },
}));
const mockApi = jest.mocked(apiFetch);

const campaign = (id: string, status = "running"): EmailCampaign => ({
  id,
  name: `Campagne ${id}`,
  status,
  sequence_id: "sequence-1",
  sequence_name: "Découverte",
  brevo_list_ids: [7],
  scheduled_at: null,
  current_step: 0,
  recipient_count: 20,
  sent_count: 10,
  created_at: "2026-10-20T10:00:00Z",
});
const stats = (id: string): CampaignStats => ({
  campaign_id: id,
  campaign_name: `Campagne ${id}`,
  status: "running",
  total_recipients: 20,
  steps: [
    {
      step_position: 0,
      template_name: "Présentation",
      delay_days: 0,
      sent: 10,
      opened: 5,
      clicked: 2,
      clicked_machine: 3,
      bounced: 1,
      unsubscribed: 0,
      branches: [
        {
          condition: "not_opened",
          template_name: "Relance",
          sent: 4,
          opened: 2,
          clicked: 1,
          clicked_machine: 0,
          bounced: 0,
          unsubscribed: 0,
        },
      ],
    },
  ],
});

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn();
  Element.prototype.setPointerCapture = jest.fn();
  Element.prototype.releasePointerCapture = jest.fn();
});
beforeEach(() => {
  mockApi.mockReset();
  window.history.replaceState(null, "", "/admin/emailing");
  mockApi.mockImplementation(async (path) => {
    if (path === "/admin/emailing/campaigns")
      return [campaign("A"), campaign("B", "paused")];
    if (path === "/admin/emailing/sequences")
      return [
        { id: "sequence-1", name: "Découverte", status: "draft", steps: [] },
      ];
    if (path === "/admin/emailing/lists")
      return [
        {
          id: 7,
          name: "Prospects RH",
          total_subscribers: 20,
          total_blacklisted: 0,
        },
      ];
    if (path === "/admin/emailing/templates") return [];
    if (path.endsWith("/stats")) return stats(path.includes("/A/") ? "A" : "B");
    if (path.endsWith("/waves"))
      return {
        campaign_id: "A",
        status: "running",
        total_recipients: 20,
        pending_count: 20,
        daily_limit: 300,
        wave_max_size: 100,
        waves: [],
      };
    if (path.includes("/waves/preview")) return [];
    throw new Error(`Unexpected endpoint: ${path}`);
  });
});

test("keeps the preparation resources on one page and records the selected section", async () => {
  render(<EmailingSetup />);
  expect(await screen.findByText("Campagne A")).toBeInTheDocument();
  expect(screen.getAllByRole("tab")).toHaveLength(4);
  expect(screen.getByRole("tab", { name: /4\. Campagnes/ })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  fireEvent.keyDown(screen.getByRole("tab", { name: /Modèles d’emails/ }), {
    key: "Enter",
  });
  expect(await screen.findByText("Aucun modèle créé")).toBeInTheDocument();
  expect(window.location.search).toBe("?section=templates");
  fireEvent.click(screen.getByRole("button", { name: "Séquences" }));
  expect(await screen.findByText("Découverte")).toBeInTheDocument();
  expect(window.location.search).toBe("?section=sequences");
  expect(mockApi.mock.calls.every(([, options]) => !options?.method)).toBe(
    true
  );
});

test("programming opens the existing wave flow without triggering an immediate send", async () => {
  render(<CampaignsPanel onPrepare={jest.fn()} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Programmer les envois" })
  );
  expect(
    await screen.findByRole("dialog", { name: "Envois — Campagne A" })
  ).toBeInTheDocument();
  expect(await screen.findByLabelText("Combien de contacts")).toHaveValue(20);
  expect(
    screen.getByRole("button", { name: "Programmer cet envoi" })
  ).toBeDisabled();
  expect(mockApi).toHaveBeenCalledWith("/admin/emailing/campaigns/A/waves", {
    token: "test-token",
  });
  expect(
    mockApi.mock.calls.some(([path]) => path === "/admin/emailing/run")
  ).toBe(false);
  const scheduledAt = new Date(Date.now() + 86_400_000);
  scheduledAt.setMinutes(scheduledAt.getMinutes() - scheduledAt.getTimezoneOffset());
  const localDate = scheduledAt.toISOString().slice(0, 16);
  fireEvent.change(screen.getByLabelText("Quand (date et heure)"), { target: { value: localDate } });
  fireEvent.change(screen.getByLabelText("Combien de contacts"), { target: { value: "12" } });
  fireEvent.click(screen.getByRole("button", { name: "Programmer cet envoi" }));
  await waitFor(() => expect(mockApi).toHaveBeenCalledWith("/admin/emailing/campaigns/A/waves", {
    method: "POST", token: "test-token", body: JSON.stringify({ count: 12, scheduled_at: new Date(localDate).toISOString() }),
  }));
});

test("provides a statistics link for a paused campaign", async () => {
  render(<CampaignsPanel onPrepare={jest.fn()} />);
  const trigger = await screen.findByRole("button", {
    name: "Actions pour Campagne B",
  });
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(
    await screen.findByRole("menuitem", { name: "Voir les statistiques" })
  ).toHaveAttribute("href", "/admin/emailing/stats?campaign=B");
});

test("loads a linked campaign and calculates totals without counting branches twice", async () => {
  render(<EmailingStats initialCampaign="B" />);
  expect(
    await screen.findByRole("heading", { name: "Campagne B" })
  ).toBeInTheDocument();
  const sentCard = screen
    .getByText("Emails envoyés")
    .closest('[data-slot="card"]') as HTMLElement;
  expect(within(sentCard).getByText("10")).toBeInTheDocument();
  const openCard = screen
    .getByText("Taux d’ouverture")
    .closest('[data-slot="card"]') as HTMLElement;
  expect(within(openCard).getByText("50 %")).toBeInTheDocument();
  expect(screen.getByText("3 bots filtrés")).toBeInTheDocument();
  expect(screen.getByText("Relance")).toBeInTheDocument();
  expect(mockApi).toHaveBeenCalledWith("/admin/emailing/campaigns/B/stats", {
    token: "test-token",
  });
  expect(mockApi.mock.calls.some(([path]) => path.includes("/A/stats"))).toBe(
    false
  );
});

test("never replaces the selected campaign with a late response from another campaign", async () => {
  let resolveA!: (value: CampaignStats) => void;
  mockApi.mockImplementation(async (path) => {
    if (path === "/admin/emailing/campaigns")
      return [campaign("A"), campaign("B")];
    if (path === "/admin/emailing/campaigns/A/stats")
      return new Promise<CampaignStats>((resolve) => {
        resolveA = resolve;
      });
    if (path === "/admin/emailing/campaigns/B/stats") return stats("B");
    throw new Error(`Unexpected endpoint: ${path}`);
  });
  render(<EmailingStats initialCampaign="A" />);
  const select = screen.getByRole("combobox", { name: "Campagne à analyser" });
  await waitFor(() => expect(select).not.toBeDisabled());
  fireEvent.keyDown(select, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "Campagne B" }));
  expect(
    await screen.findByRole("heading", { name: "Campagne B" })
  ).toBeInTheDocument();
  await act(async () => {
    resolveA(stats("A"));
  });
  expect(
    screen.queryByRole("heading", { name: "Campagne A" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Campagne B" })
  ).toBeInTheDocument();
  expect(window.location.search).toBe("?campaign=B");
});

test("shows a technical statistics error and allows an explicit retry", async () => {
  mockApi.mockRejectedValueOnce(new Error("Network unavailable"));
  render(<EmailingStats />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Impossible de charger la liste des campagnes."
  );
  expect(
    screen.queryByText("Vos résultats apparaîtront ici")
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  expect(
    await screen.findByRole("heading", { name: "Campagne A" })
  ).toBeInTheDocument();
});

test("offers campaign preparation when there are no campaigns", async () => {
  mockApi.mockResolvedValueOnce([]);
  render(<EmailingStats />);
  expect(
    await screen.findByText("Vos résultats apparaîtront ici")
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Préparer une campagne" })
  ).toHaveAttribute("href", "/admin/emailing");
});
