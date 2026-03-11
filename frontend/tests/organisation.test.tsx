import { render, screen } from "@testing-library/react";

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
  OrgProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

jest.mock("@/lib/api", () => ({
  apiFetch: jest.fn(),
}));

import OrganisationPage from "@/app/(dashboard)/organisation/page";

describe("OrganisationPage", () => {
  it("renders empty state when no org selected", () => {
    render(<OrganisationPage />);
    expect(screen.getByText("Organisation")).toBeInTheDocument();
    expect(
      screen.getByText(/Aucune organisation sélectionnée/)
    ).toBeInTheDocument();
  });
});
