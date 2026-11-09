import { apiFetch } from "@/lib/api";
import {
  setupOrganisation,
  type OrganisationSetupProgress,
} from "@/lib/organisation-setup";

jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
const request = apiFetch as jest.Mock;
const organisation = { id: "org-1", name: "Audit" };
const data = {
  name: "Audit",
  account_id: "workspace-1",
  profil_metier: "dirigeant",
};

beforeEach(() => request.mockReset());

it("does not create an organisation when saving the profile failed", async () => {
  request.mockRejectedValueOnce(new Error("Profile unavailable"));
  await expect(setupOrganisation(data, "token")).rejects.toThrow(
    "Profile unavailable"
  );
  expect(request).toHaveBeenCalledTimes(1);
  expect(request.mock.calls[0][0]).toBe("/users/me");
  request.mockResolvedValueOnce({}).mockResolvedValueOnce(organisation);
  await setupOrganisation(data, "token");
  expect(
    request.mock.calls.filter(([path]) => path === "/organisations/")
  ).toHaveLength(1);
});

it("retains successful writes and reports convention errors on manual retry", async () => {
  const progress: OrganisationSetupProgress = {};
  const input = {
    ...data,
    selectedCcn: [
      { idcc: "1486", titre: "Syntec", titre_court: "Syntec", etat: null },
    ],
  };
  request
    .mockResolvedValueOnce({})
    .mockResolvedValueOnce(organisation)
    .mockRejectedValueOnce(new Error("Convention unavailable"));
  const first = await setupOrganisation(input, "token", progress);
  expect(first.organisation).toEqual(organisation);
  expect(first.warnings).toEqual(["IDCC 1486 : Convention unavailable"]);
  request.mockResolvedValueOnce({});
  const second = await setupOrganisation(input, "token", progress);
  expect(second.warnings).toEqual([]);
  expect(
    request.mock.calls.filter(([path]) => path === "/organisations/")
  ).toHaveLength(1);
  expect(
    request.mock.calls.filter(([path]) => path === "/users/me")
  ).toHaveLength(1);
  expect(
    JSON.parse(
      request.mock.calls.find(([path]) => path === "/organisations/")![1].body
    )
  ).toMatchObject({ account_id: "workspace-1" });
});
