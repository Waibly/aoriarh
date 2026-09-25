import { streamMessage, updateConversationCaseEntry } from "@/lib/chat-api";
import { apiFetch, authFetch } from "@/lib/api";
import { TextDecoder as NodeTextDecoder } from "util";

jest.mock("@/lib/api", () => ({
  apiFetch: jest.fn(),
  authFetch: jest.fn(),
}));

const fetchWithAuth = authFetch as jest.Mock;
const fetchApi = apiFetch as jest.Mock;

Object.defineProperty(global, "TextDecoder", { value: NodeTextDecoder });

test("forwards a case_file_updated SSE event without altering its payload", async () => {
  const event = {
    conversation_id: "conversation-1",
    case_file_id: "case-1",
    version: 3,
  };
  const bytes = Uint8Array.from(
    Buffer.from(`event: case_file_updated\ndata: ${JSON.stringify(event)}\n\n`)
  );
  const releaseLock = jest.fn();
  const read = jest
    .fn()
    .mockResolvedValueOnce({ done: false, value: bytes })
    .mockResolvedValueOnce({ done: true, value: undefined });
  fetchWithAuth.mockResolvedValue({
    ok: true,
    body: { getReader: () => ({ read, releaseLock }) },
  });
  const onCaseFileUpdated = jest.fn();

  await streamMessage("conversation-1", "Question", "token", {
    onSources: jest.fn(),
    onDelta: jest.fn(),
    onDone: jest.fn(),
    onError: jest.fn(),
    onCaseFileUpdated,
  });

  expect(onCaseFileUpdated).toHaveBeenCalledWith(event);
  expect(releaseLock).toHaveBeenCalledTimes(1);
});

test("sends a case correction to the versioned entry endpoint", async () => {
  fetchApi.mockResolvedValue({ version: 8 });

  await updateConversationCaseEntry("conversation-1", "entry-1", "token", {
    operation: "correct",
    expected_case_version: 7,
    value: "3 200 €",
    comment: "Vérifié",
  });

  expect(fetchApi).toHaveBeenCalledWith(
    "/conversations/conversation-1/case-file/entries/entry-1/revisions",
    {
      method: "POST",
      body: JSON.stringify({
        operation: "correct",
        expected_case_version: 7,
        value: "3 200 €",
        comment: "Vérifié",
      }),
      token: "token",
    }
  );
});

test("keeps interruption warnings separate from content and completion", async () => {
  const measure = jest.fn();
  Object.defineProperty(performance, "measure", { configurable: true, value: measure });
  const bytes = Uint8Array.from(Buffer.from(
    'event: chat_delta\ndata: {"content":"Texte original"}\n\n' +
    'event: chat_warning\ndata: {"message":"Flux interrompu"}\n\n' +
    'event: chat_done\ndata: {"answer_id":"saved","message_id":"user"}\n\n'
  ));
  const read = jest.fn().mockResolvedValueOnce({ done: false, value: bytes })
    .mockResolvedValueOnce({ done: true });
  fetchWithAuth.mockResolvedValue({ ok: true, body: {
    getReader: () => ({ read, releaseLock: jest.fn() }),
  } });
  const callbacks = { onDelta: jest.fn(), onSources: jest.fn(), onDone: jest.fn(),
    onError: jest.fn(), onWarning: jest.fn() };
  await streamMessage("conversation-1", "Question", "token", callbacks);
  expect(callbacks.onDelta).toHaveBeenCalledTimes(1);
  expect(callbacks.onDelta).toHaveBeenCalledWith("Texte original");
  expect(callbacks.onWarning).toHaveBeenCalledWith("Flux interrompu");
  expect(callbacks.onError).not.toHaveBeenCalled();
  expect(callbacks.onDone).toHaveBeenCalledTimes(1);
  expect(measure.mock.calls.map(([name]) => name)).toEqual([
    "aoriarh.chat.headers", "aoriarh.chat.first_text", "aoriarh.chat.done",
  ]);
});
