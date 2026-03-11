import { render, screen, act } from "@testing-library/react";

jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: {
      user: {
        id: "1",
        email: "admin@test.com",
        full_name: "Admin",
        role: "admin",
      },
      access_token: "fake-token",
    },
  }),
  SessionProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

jest.mock("@/lib/org-context", () => ({
  useOrg: () => ({
    organisations: [],
    currentOrg: null,
    setCurrentOrgId: jest.fn(),
    loading: false,
    refetchOrgs: jest.fn(),
  }),
  OrgProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

jest.mock("@/lib/api", () => ({
  apiFetch: jest.fn().mockResolvedValue([]),
}));

import DocumentsCommunsPage from "@/app/(dashboard)/admin/documents-communs/page";

describe("DocumentsCommunsPage", () => {
  it("renders the page title", async () => {
    await act(async () => {
      render(<DocumentsCommunsPage />);
    });
    expect(screen.getByText("Documents communs")).toBeInTheDocument();
  });

  it("renders the card header", async () => {
    await act(async () => {
      render(<DocumentsCommunsPage />);
    });
    expect(screen.getByText("Base documentaire commune")).toBeInTheDocument();
  });

  it("renders the upload button", async () => {
    await act(async () => {
      render(<DocumentsCommunsPage />);
    });
    expect(
      screen.getByRole("button", { name: /Ajouter un document/i })
    ).toBeInTheDocument();
  });

  it("does not render stats cards", async () => {
    await act(async () => {
      render(<DocumentsCommunsPage />);
    });
    // Stats cards were removed — verify they're not present
    expect(screen.queryByText("Stockage")).not.toBeInTheDocument();
  });
});
