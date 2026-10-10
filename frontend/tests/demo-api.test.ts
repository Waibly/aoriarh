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
