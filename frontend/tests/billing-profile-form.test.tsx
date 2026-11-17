import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BillingProfileForm } from "@/components/billing-profile-form";
import { fetchBillingProfile, saveBillingProfile } from "@/lib/billing-api";

jest.mock("@/lib/billing-api", () => ({
  fetchBillingProfile: jest.fn(), saveBillingProfile: jest.fn(),
}));
jest.mock("@/lib/toast", () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

const profile = {
  business_name: "Entreprise test", line1: "1 rue du Test", line2: "",
  postal_code: "97410", city: "Saint-Pierre", country: "RE", professional: true,
};

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(fetchBillingProfile).mockResolvedValue(profile);
  jest.mocked(saveBillingProfile).mockResolvedValue(profile);
});

it("loads the billing establishment and invalidates readiness when it is edited", async () => {
  const ready = jest.fn();
  render(<BillingProfileForm token="owner-token" onReady={ready} />);
  expect(await screen.findByDisplayValue("Entreprise test")).toBeInTheDocument();
  expect(ready).toHaveBeenLastCalledWith(true);
  fireEvent.change(screen.getByLabelText("Code postal"), { target: { value: "97420" } });
  expect(ready).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer les coordonnées" }));
  await waitFor(() => expect(saveBillingProfile).toHaveBeenCalledWith("owner-token", {
    ...profile, postal_code: "97420",
  }));
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(true));
});

it("blocks Polynesia even when entered as France with a Polynesian postal code", async () => {
  render(<BillingProfileForm token="owner-token" onReady={jest.fn()} />);
  await screen.findByDisplayValue("Entreprise test");
  fireEvent.change(screen.getByLabelText(/Pays ou territoire/), { target: { value: "FR" } });
  fireEvent.change(screen.getByLabelText("Code postal"), { target: { value: "98713" } });
  expect(screen.getByRole("alert")).toHaveTextContent(/pas disponibles/);
  expect(screen.getByRole("button", { name: "Enregistrer les coordonnées" })).toBeDisabled();
  expect(saveBillingProfile).not.toHaveBeenCalled();
});

it("does not enable checkout when saving the fiscal address fails", async () => {
  const ready = jest.fn();
  jest.mocked(saveBillingProfile).mockRejectedValue(new Error("Stripe indisponible"));
  render(<BillingProfileForm token="owner-token" onReady={ready} />);
  await screen.findByDisplayValue("Entreprise test");
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer les coordonnées" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Stripe indisponible");
  expect(ready).toHaveBeenLastCalledWith(false);
});
