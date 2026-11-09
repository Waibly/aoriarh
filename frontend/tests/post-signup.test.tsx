import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import PostSignupPage from "@/app/post-signup/page";
import { apiFetch } from "@/lib/api";

const mockRouter = { replace: jest.fn(), push: jest.fn() };
const mockSession = {
  status: "authenticated",
  data: { access_token: "token" },
};
jest.mock("next/navigation", () => ({ useRouter: () => mockRouter }));
jest.mock("next-auth/react", () => ({ useSession: () => mockSession }));
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
jest.mock("@/lib/signup-flow", () => ({
  readSignupCookie: () => null,
  clearSignupCookie: jest.fn(),
  safeAppCallback: () => null,
  redeemPendingPlan: jest.fn().mockResolvedValue(undefined),
}));
const request = apiFetch as jest.Mock;
beforeEach(() => {
  request.mockReset();
  mockRouter.replace.mockClear();
});

it("routes a new Google user to the organisation onboarding", async () => {
  request.mockResolvedValueOnce([]).mockResolvedValueOnce({});
  render(<PostSignupPage />);
  await waitFor(() =>
    expect(mockRouter.replace).toHaveBeenCalledWith("/register?onboard=1")
  );
});

it("takes an invited Google user to their pending invitation", async () => {
  request
    .mockResolvedValueOnce([])
    .mockResolvedValueOnce({ pending_invitation_token: "invitation" });
  render(<PostSignupPage />);
  await waitFor(() =>
    expect(mockRouter.replace).toHaveBeenCalledWith("/invite/accept/invitation")
  );
});

it("shows a technical error and permits retry without pretending the account is empty", async () => {
  request.mockRejectedValueOnce(new Error("Service unavailable"));
  render(<PostSignupPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Service unavailable"
  );
  expect(mockRouter.replace).not.toHaveBeenCalled();
  request.mockResolvedValueOnce([]).mockResolvedValueOnce({});
  fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() =>
    expect(mockRouter.replace).toHaveBeenCalledWith("/register?onboard=1")
  );
});
