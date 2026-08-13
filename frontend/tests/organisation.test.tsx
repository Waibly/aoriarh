import { render, screen } from "@testing-library/react";

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    refresh: jest.fn(),
  }),
}));

jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: {
      user: {
        id: "1",
        email: "test@test.com",
        full_name: "Test",
        role: "manager",
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
  OrgProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock("@/lib/api", () => ({
  apiFetch: jest.fn(),
}));

import OrganisationPage from "@/app/(dashboard)/organisation/page";

describe("OrganisationPage", () => {
  it("renders empty state when no org selected", () => {
    render(<OrganisationPage />);
    expect(
      screen.getByRole("heading", { name: "Organisations" })
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Aucune organisation pour l'instant/)
    ).toBeInTheDocument();
  });
});
