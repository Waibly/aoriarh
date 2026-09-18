import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NewConversation } from "@/components/chat/new-conversation";
import { createConversation, uploadChatDocument, getConversation, streamMessage } from "@/lib/chat-api";
import { searchChatLibrary, prepareLibraryDocument } from "@/lib/chat-document-library";
import { toast } from "sonner";

jest.mock("next-auth/react", () => ({ useSession: () => ({ data: { access_token: "token" } }) }));
jest.mock("next/dynamic", () => () => function Messages() { return <div />; });
jest.mock("@/components/chat/search-details", () => ({ SearchDetailsPanel: () => null }));
jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));
jest.mock("@/lib/chat-api", () => ({
  createConversation: jest.fn(), uploadChatDocument: jest.fn(), getConversation: jest.fn(),
  streamMessage: jest.fn(), updateMessageFeedback: jest.fn(),
}));
jest.mock("@/lib/chat-document-library", () => ({ searchChatLibrary: jest.fn(), prepareLibraryDocument: jest.fn() }));

const conversation = { id: "conversation", document_attachments_enabled: true, messages: [] };
const reference = { document_id: "doc", extraction_id: "version", name: "contrat.txt" };
const file = new File(["Salaire : 2400 euros"], "contrat.txt", { type: "text/plain" });
function mount() {
  const onSaved = jest.fn();
  const view = render(<StrictMode><NewConversation organisationId="org" token="token" onSaved={onSaved} /></StrictMode>);
  return { ...view, onSaved };
}
function typeAndSend(text = "Lis ce document") {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: text } });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
}
beforeEach(() => {
  jest.clearAllMocks();
  (createConversation as jest.Mock).mockResolvedValue(conversation);
  (uploadChatDocument as jest.Mock).mockResolvedValue(reference);
  (prepareLibraryDocument as jest.Mock).mockResolvedValue(reference);
  (getConversation as jest.Mock).mockResolvedValue(conversation);
  (searchChatLibrary as jest.Mock).mockResolvedValue({ items: [{ ...reference, source_sha256: "a".repeat(64),
    uploaded_at: "2026-03-01T10:00:00Z", file_format: "txt" }], has_more: false });
  (streamMessage as jest.Mock).mockResolvedValue(undefined);
});

it("shows attachment controls immediately without creating a conversation on page load", () => {
  mount();
  expect(screen.getByLabelText("Joindre un document")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Documents de l’entreprise" })).toBeEnabled();
  expect(createConversation).not.toHaveBeenCalled();
});

it("sends the first message exactly once with its uploaded reference, even with a late history fetch", async () => {
  let history!: (value: unknown) => void;
  (getConversation as jest.Mock).mockImplementation(() => new Promise((resolve) => { history = resolve; }));
  const { container, onSaved } = mount();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Lis ce document" } });
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  expect(await screen.findByText("contrat.txt")).toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveValue("Lis ce document");
  expect(streamMessage).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  await waitFor(() => expect(streamMessage).toHaveBeenCalledTimes(1));
  expect((streamMessage as jest.Mock).mock.calls[0][5]).toEqual([reference]);
  expect((streamMessage as jest.Mock).mock.calls[0][1]).toBe("Lis ce document");
  expect(createConversation).toHaveBeenCalledTimes(1);
  expect(onSaved).not.toHaveBeenCalled();
  await act(async () => { history(conversation); });
  expect(streamMessage).toHaveBeenCalledTimes(1);
  await act(async () => {
    const callbacks = (streamMessage as jest.Mock).mock.calls[0][3];
    callbacks.onDelta("  Réponse originale\n");
    callbacks.onDone({ message_id: "m", answer_id: "a" });
  });
  expect(onSaved).toHaveBeenCalledWith("conversation");
});

it("selects an enterprise document before the first message, without uploading again", async () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Documents de l’entreprise" }));
  fireEvent.click(await screen.findByRole("button", { name: "Choisir contrat.txt" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  typeAndSend();
  await waitFor(() => expect(streamMessage).toHaveBeenCalledTimes(1));
  expect((streamMessage as jest.Mock).mock.calls[0][5]).toEqual([reference]);
  expect(createConversation).toHaveBeenCalledTimes(1);
  expect(uploadChatDocument).not.toHaveBeenCalled();
});

it("keeps the text on creation failure and does not send or navigate to a fake conversation", async () => {
  (createConversation as jest.Mock).mockRejectedValueOnce(new Error("Connexion interrompue"));
  const { onSaved } = mount();
  typeAndSend("Mon texte à conserver");
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Connexion interrompue"));
  expect(screen.getByRole("textbox")).toHaveValue("Mon texte à conserver");
  expect(streamMessage).not.toHaveBeenCalled();
  expect(onSaved).not.toHaveBeenCalled();
});

it("blocks sending while a file is being prepared", async () => {
  let finish!: (value: unknown) => void;
  (uploadChatDocument as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const { container } = mount();
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  await waitFor(() => expect(uploadChatDocument).toHaveBeenCalled());
  expect(screen.getByRole("textbox")).toBeDisabled();
  expect(streamMessage).not.toHaveBeenCalled();
  await act(async () => { finish(reference); });
  expect(screen.getByRole("textbox")).toBeEnabled();
});

it("keeps the first-message path working without documents", async () => {
  mount();
  typeAndSend("Une question RH");
  await waitFor(() => expect(streamMessage).toHaveBeenCalledTimes(1));
  expect((streamMessage as jest.Mock).mock.calls[0][5]).toEqual([]);
  expect(uploadChatDocument).not.toHaveBeenCalled();
});

it("removes a selected attachment before sending the first message", async () => {
  const { container } = mount();
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  fireEvent.click(await screen.findByLabelText("Retirer contrat.txt"));
  typeAndSend();
  await waitFor(() => expect(streamMessage).toHaveBeenCalledTimes(1));
  expect((streamMessage as jest.Mock).mock.calls[0][5]).toEqual([]);
});

it("does not create twice when Enter is pressed twice", async () => {
  mount();
  typeAndSend();
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  await waitFor(() => expect(streamMessage).toHaveBeenCalledTimes(1));
  expect(createConversation).toHaveBeenCalledTimes(1);
});

it("does not carry a late attachment into another organisation", async () => {
  let finish!: (value: unknown) => void;
  (uploadChatDocument as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  const { container, rerender } = mount();
  fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
  await waitFor(() => expect(uploadChatDocument).toHaveBeenCalled());
  rerender(<NewConversation key="other" organisationId="other" token="token" onSaved={jest.fn()} />);
  await act(async () => { finish(reference); });
  expect(screen.queryByText("contrat.txt")).not.toBeInTheDocument();
  expect(streamMessage).not.toHaveBeenCalled();
});
