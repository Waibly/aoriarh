import { render, screen, act, waitFor } from "@testing-library/react";

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

import AdminDocumentsPage from "@/app/(dashboard)/admin/documents/page";

describe("AdminDocumentsPage", () => {
  it("renders the page title", async () => {
    await act(async () => {
      render(<AdminDocumentsPage />);
    });
    expect(screen.getByText("Tous les documents")).toBeInTheDocument();
  });

  it("renders stats cards", async () => {
    await act(async () => {
      render(<AdminDocumentsPage />);
    });
    expect(screen.getByText("Documents")).toBeInTheDocument();
    expect(screen.getByText("Stockage")).toBeInTheDocument();
  });

  it("renders empty state after loading", async () => {
    await act(async () => {
      render(<AdminDocumentsPage />);
    });
    await waitFor(() => {
      expect(screen.getByText("Aucun document.")).toBeInTheDocument();
    });
  });
});
