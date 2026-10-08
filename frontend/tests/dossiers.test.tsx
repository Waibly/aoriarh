import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CreateDossierDialog } from "@/components/dossiers/create-dossier-dialog";
import { DossierPanel } from "@/components/dossiers/dossier-panel";
import { DossierContent } from "@/components/dossiers/dossier-content";
import { apiFetch } from "@/lib/api";
import { getDossier, dossierOperation, type DossierDetail } from "@/lib/dossiers-api";

const push = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
jest.mock("@/lib/chat-api", () => ({ getConversationCaseFile: jest.fn() }));
jest.mock("@/lib/dossiers-api", () => ({
  getDossier: jest.fn(),
  dossierOperation: jest.fn(),
  dossierChanged: jest.fn(),
  uploadDossierDocument: jest.fn(),
  downloadDossierDocument: jest.fn(),
}));
jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));

const dossier = {
  id: "dossier-1",
  organisation_id: "org-1",
  name: "Élections CSE",
  description: "",
  instructions: "",
  archived_at: null,
  version: 1,
  documents: [],
  conversations: [],
  has_more: false,
  case_file: {
    id: "case-1",
    version: 3,
    entries: [],
    documents: [],
    tasks: [],
    inherited_context: null,
  },
} as unknown as DossierDetail;

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(global.crypto, "randomUUID", {
    configurable: true,
    value: () => "creation-id",
  });
});

test("creating a dossier submits only its identity and does not start a chat", async () => {
  (apiFetch as jest.Mock).mockResolvedValue(dossier);
  render(
    <CreateDossierDialog
      open
      onOpenChange={jest.fn()}
      organisationId="org-1"
      token="token"
    />
  );
  expect(
    screen.getByRole("button", { name: "Créer le dossier" })
  ).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Nom du dossier"), {
    target: { value: "Élections CSE" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Créer le dossier" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/dossiers/dossier-1"));
  expect(apiFetch).toHaveBeenCalledTimes(1);
  const payload = JSON.parse((apiFetch as jest.Mock).mock.calls[0][1].body);
  expect(payload).toEqual({
    name: "Élections CSE",
    organisation_id: "org-1",
    creation_key: "creation-id",
  });
  expect(
    screen.queryByText("Ajouter à un dossier existant")
  ).not.toBeInTheDocument();
});

test("a failed information save retains the exact user input and exposes the error", async () => {
  (dossierOperation as jest.Mock).mockRejectedValue(
    new Error("Le dossier a changé. Rechargez-le.")
  );
  render(
    <DossierContent
      dossier={dossier}
      token="token"
      tab="informations"
      onChange={jest.fn()}
    />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Ajouter une information" })
  );
  fireEvent.change(screen.getByLabelText("Intitulé"), {
    target: { value: "Date" },
  });
  const original = "  Ligne une\nLigne deux  ";
  fireEvent.change(screen.getByLabelText("Information"), {
    target: { value: original },
  });
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() =>
    expect(screen.getAllByRole("alert").length).toBeGreaterThan(0)
  );
  expect(screen.getByLabelText("Information")).toHaveValue(original);
  expect(dossierOperation).toHaveBeenCalledWith(
    "dossier-1",
    "token",
    "/entries",
    {
      label: "Date",
      value: original,
      expected_case_version: 3,
    }
  );
});

test("archived dossier remains readable without edit or import actions", () => {
  render(
    <DossierContent
      dossier={{ ...dossier, archived_at: "2026-10-07" }}
      token="token"
      tab="documents"
      onChange={jest.fn()}
    />
  );
  expect(
    screen.getByText(/Les fichiers importés restent dans ce dossier/)
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Ajouter un document" })
  ).not.toBeInTheDocument();
});

test("canceling navigation keeps an edited dossier description", () => {
  const changeTab = jest.fn();
  const confirm = jest.spyOn(window, "confirm").mockReturnValue(false);
  render(
    <>
      <button role="tab" onClick={changeTab}>
        Documents voisins
      </button>
      <DossierContent
        dossier={dossier}
        token="token"
        tab="informations"
        onChange={jest.fn()}
      />
    </>
  );
  fireEvent.click(screen.getByRole("button", { name: "Modifier" }));
  fireEvent.change(screen.getByLabelText("Description", { exact: true }), {
    target: { value: "Brouillon" },
  });
  fireEvent.click(screen.getByRole("tab", { name: "Documents voisins" }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(changeTab).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Description", { exact: true })).toHaveValue(
    "Brouillon"
  );
  confirm.mockRestore();
});


test("panel refresh failures preserve unsaved information", async () => {
  (getDossier as jest.Mock).mockResolvedValueOnce(dossier);
  const props = { id: dossier.id, token: "token", open: true, onOpenChange: jest.fn() };
  const { rerender } = render(<DossierPanel {...props} refreshVersion={1} />);
  fireEvent.click(await screen.findByRole("button", { name: "Modifier" }));
  fireEvent.change(screen.getByLabelText("Description", { exact: true }), {
    target: { value: "Description non enregistrée" },
  });
  (getDossier as jest.Mock).mockRejectedValueOnce(new Error("Réseau indisponible"));
  rerender(<DossierPanel {...props} refreshVersion={2} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Réseau indisponible");
  expect(screen.getByLabelText("Description", { exact: true })).toHaveValue("Description non enregistrée");
  (getDossier as jest.Mock).mockResolvedValueOnce({ ...dossier, description: "Version distante" });
  fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Description", { exact: true })).toHaveValue("Description non enregistrée");
});
