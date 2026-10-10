import { streamPublicAsk } from "@/lib/demo-api";

jest.mock("@/lib/api", () => ({ API_BASE_URL: "https://api.example.test/api/v1" }));

const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; });

test("public demo sends only the fields accepted by the strict API schema", async () => {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: false,
    json: async () => ({ detail: "Vérification anti-robot échouée." }),
  });
  global.fetch = fetchMock;
  const onError = jest.fn();
  const message = "À quel moment un employeur peut mettre en place une enquête interne ?";

  await streamPublicAsk({ message, turnstileToken: "test-token" }, {
    onSources: jest.fn(), onDelta: jest.fn(), onDone: jest.fn(), onError,
  });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("https://api.example.test/api/v1/public/ask");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ message, turnstile_token: "test-token" });
  expect(onError).toHaveBeenCalledWith("Vérification anti-robot échouée.");
});

const { TextDecoder: NodeTextDecoder } = jest.requireActual('util');
Object.defineProperty(global, 'TextDecoder', { value: NodeTextDecoder });

function streamResponse(frames: string[]) {
  const read = jest.fn();
  for (const frame of frames) read.mockResolvedValueOnce({ done: false, value: Uint8Array.from(Buffer.from(frame)) });
  read.mockResolvedValue({ done: true });
  global.fetch = jest.fn().mockResolvedValue({ ok: true, body: {
    getReader: () => ({ read, releaseLock: jest.fn() }),
  } });
}
const callbacks = () => ({ onSources: jest.fn(), onDelta: jest.fn(), onDone: jest.fn(), onError: jest.fn() });

test('reports a truncated stream and preserves received content verbatim', async () => {
  const raw = '  Texte brut\n\n';
  streamResponse([`event: chat_delta\ndata: ${JSON.stringify({content:raw})}\n\n`]);
  const cb = callbacks();
  await streamPublicAsk({message:'Question'}, cb);
  expect(cb.onDelta).toHaveBeenCalledWith(raw);
  expect(cb.onError).toHaveBeenCalledTimes(1);
  expect(cb.onDone).not.toHaveBeenCalled();
});

test('reports malformed SSE as a technical error', async () => {
  streamResponse(['event: chat_delta\ndata: not-json\n\n']);
  const cb = callbacks();
  await streamPublicAsk({message:'Question'}, cb);
  expect(cb.onError).toHaveBeenCalledTimes(1);
  expect(cb.onDone).not.toHaveBeenCalled();
});

test('handles split SSE frames and completion without retry', async () => {
  streamResponse(['event: chat_del', 'ta\ndata: {"content":"original"}\n\nevent: chat_done\ndata: {}\n\n']);
  const cb = callbacks();
  await streamPublicAsk({message:'Question'}, cb);
  expect(cb.onDelta).toHaveBeenCalledWith('original');
  expect(cb.onDone).toHaveBeenCalledTimes(1);
  expect(cb.onError).not.toHaveBeenCalled();
  expect(global.fetch).toHaveBeenCalledTimes(1);
});
