import { apiFetch } from "@/lib/api";
import {
  redeemPendingPlan,
  safeAppCallback,
  withSetupWarnings,
} from "@/lib/signup-flow";

jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
jest.mock("@/lib/toast", () => ({ toast: { warning: jest.fn() } }));
const request = apiFetch as jest.Mock;

beforeEach(() => {
  request.mockReset();
  document.cookie = "aoria_plan_invite_token=audit-token; path=/";
});
afterEach(() => {
  document.cookie = "aoria_plan_invite_token=; max-age=0; path=/";
});

it("keeps the invitation available when the server rejects activation", async () => {
  request.mockRejectedValueOnce(new Error("Wrong email"));
  await expect(redeemPendingPlan("token")).rejects.toThrow("Wrong email");
  expect(document.cookie).toContain("aoria_plan_invite_token=audit-token");
});

it.each(["redeemed", "already_redeemed"])(
  "clears a confirmed %s activation",
  async (status) => {
    request.mockResolvedValueOnce({ status });
    await redeemPendingPlan("token");
    expect(document.cookie).not.toContain("aoria_plan_invite_token");
  }
);

it("preserves existing destination parameters when reporting installation failures", () => {
  const result = withSetupWarnings("/chat?q=question#answer", [
    "IDCC 1486 failed",
  ]);
  const url = new URL(result, window.location.origin);
  expect(url.searchParams.get("q")).toBe("question");
  expect(url.searchParams.get("ccn_install_error")).toBe("IDCC 1486 failed");
  expect(url.hash).toBe("#answer");
});

it.each(["//outside.example", "/\\outside.example", "https://outside.example"])(
  "rejects a destination outside the application: %s",
  (path) => {
    expect(safeAppCallback(path)).toBeNull();
  }
);
