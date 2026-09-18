import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { DocumentLibrary } from "@/components/chat/document-library";
import { searchChatLibrary } from "@/lib/chat-document-library";

jest.mock("@/lib/chat-document-library", () => ({ searchChatLibrary: jest.fn() }));
const search = searchChatLibrary as jest.Mock;
const document = { document_id: "one", name: "Compte rendu mars.txt", source_type: "divers",
  uploaded_at: "2026-03-12T12:00:00Z", updated_at: "2026-03-12T12:00:00Z", file_format: "txt",
  file_size: 200, source_sha256: "a".repeat(64) };

function mount(selectedIds: string[] = [], onSelect = jest.fn().mockResolvedValue(undefined)) {
  function Harness() {
    const [open, setOpen] = useState(false);
    return <><button disabled={selectedIds.length >= 3} onClick={() => setOpen(true)}>Documents de l’entreprise</button>
      <DocumentLibrary conversationId="conversation" token="token" open={open} onOpenChange={setOpen}
        selectedIds={selectedIds} disabled={false} onSelect={onSelect} /></>;
  }
  return { ...render(<Harness />), onSelect };
}
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Documents de l’entreprise" }));
  await screen.findByText(document.name);
}
beforeEach(() => { search.mockReset(); search.mockResolvedValue({ items: [document], has_more: false }); });

it("searches only on opening or submission and never attaches automatically", async () => {
  const { onSelect } = mount();
  expect(search).not.toHaveBeenCalled();
  await open();
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Nom du document"), { target: { value: "mars" } });
  fireEvent.change(screen.getByLabelText("Déposé à partir du"), { target: { value: "2026-03-01" } });
  expect(search).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Rechercher" }));
  await waitFor(() => expect(search).toHaveBeenLastCalledWith("conversation", "token",
    { name: "mars", uploaded_from: "2026-03-01", uploaded_to: "" }, 0));
  fireEvent.click(await screen.findByRole("button", { name: `Choisir ${document.name}` }));
  await waitFor(() => expect(onSelect).toHaveBeenCalledWith(document));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("disables already attached documents and the three-piece limit", async () => {
  const { unmount } = mount(["one"]);
  await open();
  expect(screen.getByRole("button", { name: `Choisir ${document.name}` })).toBeDisabled();
  unmount();
  mount(["one", "two", "three"]);
  expect(screen.getByRole("button", { name: "Documents de l’entreprise" })).toBeDisabled();
});

it("shows preparation failure without confirming a selection", async () => {
  const onSelect = jest.fn().mockRejectedValue(new Error("Le document a changé"));
  mount([], onSelect);
  await open();
  fireEvent.click(screen.getByRole("button", { name: `Choisir ${document.name}` }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Le document a changé");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(onSelect).toHaveBeenCalledTimes(1);
});

it("clears old choices when a new search fails", async () => {
  mount();
  await open();
  search.mockRejectedValueOnce(new Error("Accès refusé"));
  fireEvent.click(screen.getByRole("button", { name: "Rechercher" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Accès refusé");
  expect(screen.queryByText(document.name)).not.toBeInTheDocument();
});

it("ignores search results arriving after closing", async () => {
  let resolve!: (value: unknown) => void;
  search.mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Documents de l’entreprise" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await act(async () => { resolve({ items: [document], has_more: false }); });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("paginates with the submitted criteria, not unsubmitted edits", async () => {
  search.mockResolvedValue({ items: [document], has_more: true });
  mount();
  await open();
  fireEvent.change(screen.getByLabelText("Nom du document"), { target: { value: "unsent edit" } });
  fireEvent.click(screen.getByRole("button", { name: "Suivants" }));
  await waitFor(() => expect(search).toHaveBeenLastCalledWith("conversation", "token",
    { name: "", uploaded_from: "", uploaded_to: "" }, 20));
});
