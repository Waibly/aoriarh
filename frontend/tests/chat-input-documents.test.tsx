import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ChatInput } from "@/components/chat/chat-input";

describe("chat documents", () => {
  it("does not expose upload when the capability is unavailable", () => {
    render(<ChatInput onSend={jest.fn()} />);
    expect(screen.queryByLabelText("Ajouter des documents")).not.toBeInTheDocument();
  });
  it("shows retained references and clears only the selected reference", () => {
    const remove = jest.fn();
    render(<ChatInput onSend={jest.fn()} onAttach={jest.fn()} onRemove={remove}
      attachments={[{ document_id: "one", extraction_id: "v1", name: "courrier.txt" }]} />);
    expect(screen.queryByText(/Retirer une pièce du chat/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Retirer courrier.txt"));
    expect(remove).toHaveBeenCalledWith("one");
  });
  it("limits selection to three active pieces without changing the message", async () => {
    const send = jest.fn();
    render(<ChatInput onSend={send} onAttach={jest.fn()}
      attachments={[1, 2, 3].map((id) => ({ document_id: String(id), extraction_id: "v1" }))} />);
    fireEvent.click(screen.getByLabelText("Ajouter des documents"));
    expect(screen.getByRole("button", { name: /Importer un fichier/ })).toBeDisabled();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Prépare un mail" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    expect(send).toHaveBeenCalledWith("Prépare un mail");
    await waitFor(() => expect(input).toHaveValue(""));
  });
  it("shows full, targeted and preparing states without technical byte limits", () => {
    render(<ChatInput onSend={jest.fn()} attachments={[
      { document_id: "short", extraction_id: "v1", name: "contrat.pdf", text_bytes: 20_000,
        reading_mode: "full", processing_status: "ready", search_status: "ready" },
      { document_id: "long", extraction_id: "v2", name: "accord.pdf", text_bytes: 120_000,
        reading_mode: "targeted", processing_status: "preparing", search_status: "preparing" },
    ]} />);
    expect(screen.getByText("Lu intégralement")).toBeVisible();
    expect(screen.getByText("Préparation de la lecture…")).toBeVisible();
    expect(screen.queryByText(/96 000|octets|budget de lecture/)).not.toBeInTheDocument();
  });
});

it("keeps sharing information in the add menu, not on the empty composer", () => {
  render(<ChatInput onSend={jest.fn()} onAttach={jest.fn()} onBrowse={jest.fn()} />);
  expect(screen.queryByText(/Ajouté aux documents/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Ajouter des documents"));
  expect(screen.getByText(/Ajouté aux documents de l’entreprise/)).toBeVisible();
  expect(screen.getByRole("button", { name: /Documents de l’entreprise/ })).toBeVisible();
  expect(screen.getByText(/Seul le texte extrait/)).not.toBeVisible();
  fireEvent.click(screen.getByText("Formats et informations"));
  expect(screen.getByText(/Seul le texte extrait/)).toBeVisible();
});
