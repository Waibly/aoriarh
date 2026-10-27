import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OrgProvider, useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import { WelcomeScreen } from "@/components/chat/welcome-screen";

jest.mock("next-auth/react", () => ({
  useSession: () => ({ data: { access_token: "test-token" } }),
}));
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
jest.mock("@/components/chat/chat-input", () => ({
  ChatInput: () => <div />,
}));

function ClientSelector() {
  const { currentOrg, setCurrentOrgId, setProfilMetier } = useOrg();
  return (
    <>
      <span data-testid="client">{currentOrg?.name}</span>
      <button onClick={() => setCurrentOrgId("client-b")}>Client B</button>
      <button onClick={() => setProfilMetier("comptable_paie")}>
        Modifier mon profil
      </button>
      <WelcomeScreen onSend={jest.fn()} />
    </>
  );
}

it("loads the personal profile with the account context and retains it when switching clients", async () => {
  localStorage.clear();
  (apiFetch as jest.Mock).mockImplementation(async (path: string) => {
    if (path === "/organisations/") {
      return [
        { id: "client-a", name: "Entreprise A" },
        { id: "client-b", name: "Entreprise B" },
      ];
    }
    return {
      workspace_name: path.includes("client-b") ? "Espace B" : "Espace A",
      profil_metier: "expert_comptable",
    };
  });
  render(
    <OrgProvider>
      <ClientSelector />
    </OrgProvider>
  );
  await screen.findByRole("button", {
    name: "Conseiller un client sur un CDD",
  });
  await waitFor(() =>
    expect(screen.getByTestId("client")).toHaveTextContent("Entreprise A")
  );
  fireEvent.click(screen.getByRole("button", { name: "Client B" }));
  await waitFor(() =>
    expect(apiFetch).toHaveBeenCalledWith(
      "/users/me?organisation_id=client-b",
      { token: "test-token" }
    )
  );
  expect(screen.getByTestId("client")).toHaveTextContent("Entreprise B");
  expect(
    screen.getByRole("button", { name: "Conseiller un client sur un CDD" })
  ).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Modifier mon profil" }));
  expect(
    screen.getByRole("button", { name: "Examiner le maintien de salaire" })
  ).toBeEnabled();
});
