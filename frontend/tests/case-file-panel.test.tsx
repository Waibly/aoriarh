import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CaseFilePanel } from "@/components/chat/case-file-panel";
import {
  getConversationCaseFile,
  importCaseHistory,
  getCaseFileEvents,
  updateConversationCaseEntry,
} from "@/lib/chat-api";

jest.mock("@/lib/chat-api", () => ({
  getConversationCaseFile: jest.fn(),
  importCaseHistory: jest.fn(),
  getCaseFileEvents: jest.fn(),
  updateConversationCaseEntry: jest.fn(),
}));

const getCaseFile = getConversationCaseFile as jest.Mock;
const updateEntry = updateConversationCaseEntry as jest.Mock;
const onOpenMessage = jest.fn();

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

const caseFile = {
  id: "case-1",
  conversation_id: "conversation-1",
  version: 4,
  status: "active",
  inherited_context: {
    nom: "Société Test",
    taille: "20-49",
    not_subject_to_ccn: false,
  },
  entries: [
    {
      id: "entry-1",
      entry_type: "fact",
      key: "salary",
      label: "Salaire mensuel",
      value_text: "3 200 €",
      value_json: null,
      status: "active",
      valid_from: null,
      valid_to: null,
      source_kind: "user_message",
      source_message_id: "message-1",
      source_document_id: null,
      source_extraction_id: null,
      source_excerpt: "Mon salaire est de 3 200 €",
      supersedes_entry_id: null,
      created_at: "2026-09-23T10:00:00Z",
      updated_at: "2026-09-23T10:00:00Z",
    },
    {
      id: "entry-old",
      entry_type: "fact",
      key: "salary",
      label: "Ancien salaire mensuel",
      value_text: "3 000 €",
      value_json: null,
      status: "superseded",
      valid_from: null,
      valid_to: null,
      source_kind: "user_message",
      source_message_id: "message-old",
      source_document_id: null,
      source_extraction_id: null,
      source_excerpt: null,
      supersedes_entry_id: null,
      created_at: "2026-09-22T10:00:00Z",
      updated_at: "2026-09-23T10:00:00Z",
    },
  ],
  tasks: [
    {
      id: "task-1",
      task_type: "calculation",
      question: "Calculer les indemnités",
      status: "pending",
      depends_on: [],
      relevant_entry_ids: ["entry-1"],
      required_document_ids: [],
      created_from_message_id: "message-1",
      result_message_id: null,
      created_at: "2026-09-23T10:00:00Z",
      updated_at: "2026-09-23T10:00:00Z",
    },
  ],
  documents: [],
  created_at: "2026-09-22T10:00:00Z",
  updated_at: "2026-09-23T10:00:00Z",
};

function renderPanel() {
  return render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
}

test("groups uncertainty separately and accepts an explicitly confirmed assumption", async () => {
  getCaseFile.mockResolvedValue({
    ...caseFile,
    inherited_context: null,
    entries: [
      {
        ...caseFile.entries[0],
        id: "uncertain",
        status: "contested",
        value_text: "Date incertaine",
      },
      {
        ...caseFile.entries[0],
        id: "confirmed",
        entry_type: "assumption",
        status: "confirmed",
        value_text: "Fait confirmé",
      },
    ],
  });
  renderPanel();
  const uncertain = await screen.findByText("Date incertaine");
  expect(uncertain.closest("section")).toHaveAttribute(
    "aria-labelledby",
    "case-check-heading"
  );
  expect(screen.getByText("Fait confirmé").closest("section")).toHaveAttribute(
    "aria-labelledby",
    "case-facts-heading"
  );
  expect(screen.queryByText("Hypothèse à confirmer")).not.toBeInTheDocument();
});

test("preserves the exact fact text and keeps company details collapsed", async () => {
  const original = "  Première ligne\n\nDeuxième ligne  ";
  getCaseFile.mockResolvedValue({
    ...caseFile,
    entries: [{ ...caseFile.entries[0], value_text: original }],
  });
  renderPanel();
  const label = await screen.findByText("Salaire mensuel");
  expect(label.closest("article")?.querySelector("p")?.textContent).toBe(
    original
  );
  expect(screen.getByText("Société Test")).not.toBeVisible();
  fireEvent.click(screen.getByText("Profil de l’entreprise"));
  expect(screen.getByText("Société Test")).toBeVisible();
});

test("reports loading errors without exposing internal exception text", async () => {
  getCaseFile.mockRejectedValueOnce(
    new Error("internal database connection string")
  );
  renderPanel();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Le dossier n’a pas pu être actualisé."
  );
  expect(
    screen.queryByText("internal database connection string")
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  expect(await screen.findByText("3 200 €")).toBeVisible();
});

beforeEach(() => {
  getCaseFile.mockReset();
  getCaseFile.mockResolvedValue(caseFile);
  updateEntry.mockReset();
  onOpenMessage.mockReset();
  (importCaseHistory as jest.Mock).mockReset();
  (getCaseFileEvents as jest.Mock).mockReset();
});

test("keeps developer traces and internal tasks out of the user panel", async () => {
  const { baseElement } = render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
  await screen.findByText("Société Test");
  expect(getCaseFileEvents).not.toHaveBeenCalled();
  expect(
    screen.queryByText("Historique technique et sorties originales")
  ).not.toBeInTheDocument();
  expect(screen.queryByText("Calculer les indemnités")).not.toBeInTheDocument();
  expect(baseElement.querySelector("pre")).toBeNull();
  expect(baseElement.textContent).not.toContain("not_subject_to_ccn");
  expect(baseElement.textContent).not.toContain("entry-1");
});

test("does not import old messages automatically or expose import tooling", async () => {
  render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
  await screen.findByText("Société Test");
  expect(importCaseHistory).not.toHaveBeenCalled();
  expect(
    screen.queryByText("Intégrer des messages précédents")
  ).not.toBeInTheDocument();
});

test("shows the live case file and keeps superseded information visible", async () => {
  render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );

  expect(await screen.findByText("Société Test")).toBeInTheDocument();
  expect(screen.getByText("3 200 €")).toBeInTheDocument();
  expect(screen.getByText("3 000 €")).not.toBeVisible();
  fireEvent.click(screen.getByText("Anciennes informations"));
  expect(screen.getByText("3 000 €")).toBeVisible();
  expect(screen.getByText("Ancienne information")).toBeInTheDocument();

  expect(
    screen.getAllByText("D’où vient cette information ?")[0]
  ).not.toBeVisible();
  const detailsButton = screen.getAllByRole("button", {
    name: "Détails et actions",
  })[0];
  expect(detailsButton).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(detailsButton);
  expect(detailsButton).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getAllByText("D’où vient cette information ?")[0]);
  fireEvent.click(
    screen.getAllByRole("button", { name: "Voir le message d’origine" })[0]
  );
  expect(onOpenMessage).toHaveBeenCalledWith("message-1");
});

test("reloads an open case file when its SSE version changes", async () => {
  const { rerender } = render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
  await waitFor(() => expect(getCaseFile).toHaveBeenCalledTimes(1));

  rerender(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={1}
      onOpenMessage={onOpenMessage}
    />
  );
  await waitFor(() => expect(getCaseFile).toHaveBeenCalledTimes(2));
});

test("uses the entry's exact document extraction, not the latest version", async () => {
  getCaseFile.mockResolvedValue({
    ...caseFile,
    entries: [
      {
        ...caseFile.entries[0],
        source_document_id: "doc",
        source_extraction_id: "v1",
      },
    ],
    documents: ["v1", "v2"].map((version) => ({
      id: version,
      document_id: "doc",
      extraction_id: version,
      document_name: version === "v1" ? "Bulletin original" : "Bulletin révisé",
      reading_scope: "targeted_passages",
    })),
  });
  render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
  const title = await screen.findByText("Salaire mensuel");
  const article = title.closest("article");
  expect(article?.textContent).toContain("Bulletin original");
  expect(article?.textContent).not.toContain("Bulletin révisé");
  expect(article?.textContent).toContain(
    "Seuls certains passages ont été consultés."
  );
});

test("reloads after a rejected correction without retrying the write", async () => {
  updateEntry.mockRejectedValue(new Error("Le dossier a été modifié."));
  render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );
  await screen.findByText("3 200 €");
  fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  fireEvent.change(screen.getByLabelText("Information corrigée"), {
    target: { value: "3 500 €" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(getCaseFile).toHaveBeenCalledTimes(2));
  expect(updateEntry).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Information corrigée")).toHaveValue("3 500 €");
});

test("sends explicit versioned confirmation and correction actions", async () => {
  updateEntry.mockResolvedValue({
    ...caseFile,
    version: 5,
    entries: [{ ...caseFile.entries[0], status: "confirmed" }],
  });
  render(
    <CaseFilePanel
      conversationId="conversation-1"
      token="token"
      open
      onOpenChange={jest.fn()}
      refreshVersion={0}
      onOpenMessage={onOpenMessage}
    />
  );

  await screen.findByText("3 200 €");
  fireEvent.click(screen.getAllByRole("button", { name: "Détails et actions" })[0]);
  fireEvent.click(screen.getByText("Autres actions"));
  expect(
    screen.getByRole("button", { name: "Signaler un doute" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Retirer du dossier" })
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Confirmer" }));
  await waitFor(() =>
    expect(updateEntry).toHaveBeenCalledWith(
      "conversation-1",
      "entry-1",
      "token",
      { operation: "confirm", expected_case_version: 4 }
    )
  );
  expect(await screen.findByText("Confirmé par vous")).toBeInTheDocument();

  updateEntry.mockResolvedValue({
    ...caseFile,
    version: 6,
    entries: [
      { ...caseFile.entries[0], status: "superseded" },
      {
        ...caseFile.entries[0],
        id: "entry-2",
        value_text: "3 300 €",
        status: "confirmed",
      },
    ],
  });
  fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  fireEvent.change(screen.getByLabelText("Information corrigée"), {
    target: { value: "3 300 €" },
  });
  fireEvent.change(screen.getByLabelText("Précision facultative"), {
    target: { value: "Vérifié sur le bulletin" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() =>
    expect(updateEntry).toHaveBeenLastCalledWith(
      "conversation-1",
      "entry-1",
      "token",
      {
        operation: "correct",
        expected_case_version: 5,
        value: "3 300 €",
        comment: "Vérifié sur le bulletin",
      }
    )
  );
});
