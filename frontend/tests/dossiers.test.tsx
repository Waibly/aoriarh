import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CreateDossierDialog } from "@/components/dossiers/create-dossier-dialog";
import { DossierPanel } from "@/components/dossiers/dossier-panel";
import { DossierContent } from "@/components/dossiers/dossier-content";
import { apiFetch } from "@/lib/api";
import {
  getDossier,
  dossierOperation,
  uploadDossierDocument,
  type DossierDetail,
} from "@/lib/dossiers-api";

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
jest.mock("sonner", () => ({ toast: Object.assign(jest.fn(), { error: jest.fn() }) }));

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


function file(name: string, size = 10) {
  const f = new File(["x"], name, { type: "application/pdf" });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

function openUpload(props: Partial<Parameters<typeof DossierContent>[0]> = {}) {
  const onChange = jest.fn();
  render(
    <DossierContent
      dossier={dossier}
      token="token"
      tab="documents"
      onChange={onChange}
      {...props}
    />
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Ajouter un document" })[0]
  );
  return onChange;
}

test("several dropped files are all imported, one after the other", async () => {
  let running = 0;
  let maxRunning = 0;
  (uploadDossierDocument as jest.Mock).mockImplementation(
    async (_id: string, _t: string, f: File) => {
      running += 1;
      maxRunning = Math.max(maxRunning, running);
      await new Promise((r) => setTimeout(r, 5));
      running -= 1;
      return { ...dossier, name: f.name };
    }
  );
  const onChange = openUpload();
  expect(screen.getByText("Glissez un ou plusieurs fichiers ici")).toBeVisible();
  fireEvent.drop(screen.getByText("Glissez un ou plusieurs fichiers ici").parentElement!, {
    dataTransfer: { files: [file("a.pdf"), file("b.docx"), file("c.txt")] },
  });
  await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3));
  expect(uploadDossierDocument).toHaveBeenCalledTimes(3);
  expect(
    (uploadDossierDocument as jest.Mock).mock.calls.map((c) => c[2].name)
  ).toEqual(["a.pdf", "b.docx", "c.txt"]);
  expect(maxRunning).toBe(1);
  await waitFor(() =>
    expect(screen.queryByText(/Glissez/)).not.toBeInTheDocument()
  );
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("the file picker accepts several files at once", async () => {
  (uploadDossierDocument as jest.Mock).mockResolvedValue(dossier);
  openUpload();
  const input = screen.getByTestId("dossier-file-input") as HTMLInputElement;
  expect(input.multiple).toBe(true);
  fireEvent.change(input, { target: { files: [file("a.pdf"), file("b.pdf")] } });
  await waitFor(() => expect(uploadDossierDocument).toHaveBeenCalledTimes(2));
});

test("a bad file is named and skipped while the others are imported", async () => {
  (uploadDossierDocument as jest.Mock).mockImplementation(
    async (_id: string, _t: string, f: File) => {
      if (f.name === "scan.pdf")
        throw new Error("Ce PDF ne contient pas de texte.");
      return dossier;
    }
  );
  (getDossier as jest.Mock).mockResolvedValue(dossier);
  openUpload();
  fireEvent.drop(screen.getByText(/Glissez/).parentElement!, {
    dataTransfer: {
      files: [
        file("ok.pdf"),
        file("photo.png"),
        file("gros.pdf", 11 * 1024 * 1024),
        file("scan.pdf"),
        file("ok2.docx"),
      ],
    },
  });
  const alert = await screen.findByRole("alert");
  expect(uploadDossierDocument).toHaveBeenCalledTimes(3);
  expect(alert).toHaveTextContent("2 documents ajoutés.");
  expect(alert).toHaveTextContent("photo.png : format non accepté");
  expect(alert).toHaveTextContent("gros.pdf : plus de 10 Mo");
  expect(alert).toHaveTextContent("scan.pdf : Ce PDF ne contient pas de texte.");
  expect(alert).not.toHaveTextContent("ok.pdf");
  // The window stays open so the user can retry the rejected files.
  expect(screen.getByText(/Glissez/)).toBeVisible();
});

test("replacing a document still accepts a single file only", async () => {
  const doc = {
    id: "link-1",
    document_id: "doc-1",
    extraction_id: null,
    name: "Contrat.pdf",
    description: "",
    status: "ready",
    scope: "dossier",
    file_format: "pdf",
    created_at: "2026-11-16",
  };
  (uploadDossierDocument as jest.Mock).mockResolvedValue(dossier);
  render(
    <DossierContent
      dossier={{ ...dossier, documents: [doc] } as unknown as DossierDetail}
      token="token"
      tab="documents"
      onChange={jest.fn()}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Remplacer Contrat.pdf" }));
  const input = screen.getByTestId("dossier-file-input") as HTMLInputElement;
  expect(input.multiple).toBe(false);
  fireEvent.drop(screen.getByText("Glissez le fichier ici").parentElement!, {
    dataTransfer: { files: [file("a.pdf"), file("b.pdf")] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Pour remplacer une pièce, choisissez un seul fichier."
  );
  expect(uploadDossierDocument).not.toHaveBeenCalled();
  fireEvent.drop(screen.getByText("Glissez le fichier ici").parentElement!, {
    dataTransfer: { files: [file("a.pdf")] },
  });
  await waitFor(() =>
    expect(uploadDossierDocument).toHaveBeenCalledWith(
      "dossier-1", "token", expect.any(File), "doc-1", 3
    )
  );
});
