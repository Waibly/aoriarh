import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DeleteDossierDialog } from "@/components/dossiers/delete-dossier-dialog";
import { apiFetch } from "@/lib/api";
import type { Dossier } from "@/lib/dossiers-api";
jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));
const project = { id: "project", name: "Recrutement", version: 3 } as Dossier;
beforeEach(() => jest.clearAllMocks());
it("cancels without deleting and requires explicit confirmation", () => {
  const close = jest.fn();
  render(
    <DeleteDossierDialog
      dossier={project}
      token="token"
      onClose={close}
      onDeleted={jest.fn()}
    />
  );
  expect(apiFetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  expect(close).toHaveBeenCalledTimes(1);
  expect(apiFetch).not.toHaveBeenCalled();
});
it("retains the confirmation on failure and refreshes only after successful deletion", async () => {
  const deleted = jest.fn();
  (apiFetch as jest.Mock)
    .mockRejectedValueOnce(new Error("Le dossier a changé"))
    .mockResolvedValueOnce(undefined);
  render(
    <DeleteDossierDialog
      dossier={project}
      token="token"
      onClose={jest.fn()}
      onDeleted={deleted}
    />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Supprimer définitivement" })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Le dossier a changé"
  );
  expect(deleted).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Supprimer définitivement" })
  );
  await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  expect(apiFetch).toHaveBeenLastCalledWith(
    "/dossiers/project?expected_version=3",
    { method: "DELETE", token: "token" }
  );
});
