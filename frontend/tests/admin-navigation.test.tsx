import { fireEvent, render, screen } from "@testing-library/react";
import { AdminSidebar } from "@/components/admin-sidebar";
import { IncidentsBanner } from "@/components/admin/incidents-banner";

let mockPathname = "/admin/pilotage";
let mockStaffRole: string | null = null;
jest.mock("next/navigation", () => ({ usePathname: () => mockPathname }));
jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { full_name: "Admin test", staff_role: mockStaffRole } },
  }),
  signOut: jest.fn(),
}));
jest.mock("next/image", () => ({ __esModule: true, default: () => null }));

beforeEach(() => {
  mockStaffRole = null;
  mockPathname = "/admin/pilotage";
  window.localStorage.clear();
});

test("groups the incident journal under the service and the index under tools", () => {
  mockPathname = "/admin/incidents";
  const { rerender } = render(<AdminSidebar />);
  expect(screen.getByRole("link", { name: "État du service" })).toHaveAttribute(
    "aria-current",
    "page"
  );
  expect(
    screen.queryByRole("link", { name: "Incidents & Slack" })
  ).not.toBeInTheDocument();
  mockPathname = "/admin/qdrant";
  rerender(<AdminSidebar />);
  expect(
    screen.getByRole("link", { name: "Outils techniques" })
  ).toHaveAttribute("aria-current", "page");
});

test.each(["business", "tech"])(
  "shows only the navigation for the %s profile",
  (role) => {
    mockStaffRole = role;
    render(<AdminSidebar />);
    if (role === "business") {
      expect(screen.getByRole("link", { name: "Clients" })).toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: "Outils techniques" })
      ).not.toBeInTheDocument();
    } else {
      expect(
        screen.getByRole("link", { name: "Outils techniques" })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("link", { name: "Clients" })
      ).not.toBeInTheDocument();
    }
  }
);

test("masking an alert never presents the incident as resolved", () => {
  render(
    <IncidentsBanner
      incidents={[
        {
          id: "sync-failed",
          severity: "warning",
          title: "Synchronisation interrompue",
          detail: "Un document en erreur",
          action_label: "Consulter",
          action_href: "/admin/corpus?tab=updates",
        },
      ]}
    />
  );
  fireEvent.click(
    screen.getByTitle("Masquer (réapparaît si la situation change)")
  );
  expect(screen.getByText(/1 alerte\(s\) masquée\(s\)/)).toBeInTheDocument();
  expect(
    screen.queryByText("Aucun incident en cours.")
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Réafficher" }));
  expect(screen.getByText("Synchronisation interrompue")).toBeInTheDocument();
});

test("groups all emailing views under one acquisition entry", () => {
  mockPathname = "/admin/emailing/stats";
  render(<AdminSidebar />);
  expect(screen.getByRole("link", { name: "Emailing" })).toHaveAttribute(
    "aria-current",
    "page"
  );
  expect(screen.getByRole("link", { name: "Emailing" })).toHaveAttribute(
    "href",
    "/admin/emailing"
  );
  for (const name of ["Campagnes", "Séquences", "Templates", "Listes Brevo"]) {
    expect(screen.queryByRole("link", { name })).not.toBeInTheDocument();
  }
});
