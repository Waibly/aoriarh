import { render, screen, waitFor } from "@testing-library/react";
import PromoPage from "@/app/promo/[token]/page";
import { apiFetch } from "@/lib/api";

const mockSession = {
  status: "authenticated",
  data: { access_token: "token" },
};
const mockRouter = { push: jest.fn() };
jest.mock("next/navigation", () => ({
  useParams: () => ({ token: "used-link" }),
  useRouter: () => mockRouter,
}));
jest.mock("next-auth/react", () => ({
  useSession: () => mockSession,
  signIn: jest.fn(),
}));
jest.mock("@/lib/api", () => ({ API_BASE_URL: "/api", apiFetch: jest.fn() }));

it("recognises an authenticated beneficiary even when public validation says exhausted", async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ valid: false, reason: "exhausted" }),
  });
  (apiFetch as jest.Mock).mockResolvedValueOnce({ status: "already_redeemed" });
  render(<PromoPage />);
  expect(await screen.findByText("Déjà activé")).toBeInTheDocument();
  await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  expect(apiFetch).toHaveBeenCalledWith("/plan-invitations/used-link/redeem", {
    method: "POST",
    token: "token",
  });
});
