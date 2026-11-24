/**
 * During a delivery, Caddy answers in place of the API with a "maintenance" body:
 * the user must read that message, not the generic server error.
 */

jest.mock("next-auth/react", () => ({ getSession: jest.fn(), signOut: jest.fn() }));
jest.mock("@/lib/incidents", () => ({ reportIncident: jest.fn() }));

import { apiFetch } from "./api";

function respond(status: number, body: unknown) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: status < 400,
    status,
    headers: new Headers(),
    json: () => Promise.resolve(body),
  }) as unknown as typeof fetch;
}

describe("apiFetch during a delivery", () => {
  it("shows the maintenance message sent by Caddy", async () => {
    respond(503, {
      detail: "Mise à jour de l’application en cours. Merci de patienter 1 à 2 minutes, puis réessayez.",
      code: "maintenance",
    });
    await expect(apiFetch("/users/me", { token: "t" })).rejects.toThrow(
      "Mise à jour de l’application en cours",
    );
  });

  it("keeps the generic message for an ordinary server error", async () => {
    respond(503, { detail: "Traceback interne" });
    await expect(apiFetch("/users/me", { token: "t" })).rejects.toThrow(
      "Une erreur est survenue de notre côté",
    );
  });
});
