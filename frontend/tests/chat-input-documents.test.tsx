import { fireEvent, render, screen } from "@testing-library/react";
import { ChatInput } from "@/components/chat/chat-input";

describe("chat documents", () => {
  it("does not expose upload when the capability is unavailable", () => {
    render(<ChatInput onSend={jest.fn()} />);
    expect(screen.queryByLabelText("Joindre un document")).not.toBeInTheDocument();
  });
  it("shows retained references and clears only the selected reference", () => {
    const remove = jest.fn();
    render(<ChatInput onSend={jest.fn()} onAttach={jest.fn()} onRemove={remove}
      attachments={[{ document_id: "one", extraction_id: "v1", name: "courrier.txt" }]} />);
    expect(screen.getByText(/documents de l’entreprise/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Retirer courrier.txt"));
    expect(remove).toHaveBeenCalledWith("one");
  });
  it("limits selection to three active pieces without changing the message", () => {
    const send = jest.fn();
    render(<ChatInput onSend={send} onAttach={jest.fn()}
      attachments={[1, 2, 3].map((id) => ({ document_id: String(id), extraction_id: "v1" }))} />);
    expect(screen.getByLabelText("Joindre un document")).toBeDisabled();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Prépare un mail" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });
    expect(send).toHaveBeenCalledWith("Prépare un mail");
  });
});
