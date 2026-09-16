import { render, screen } from "@testing-library/react";
import { apiFetch } from "@/lib/api";
import { IndexationErrors } from "@/app/(admin)/admin/corpus/IndexationErrors";

jest.mock("@/lib/api", () => ({ apiFetch: jest.fn() }));

test("shows both scopes and renders original errors as safe text", async () => {
  jest.mocked(apiFetch).mockResolvedValueOnce({
    total: 2, page: 1, page_size: 20,
    items: [
      { id: "common", name: "CCN commune", organisation_id: null, organisation_name: null, indexation_error: "JSON invalide" },
      { id: "org", name: "CCN Syntec", organisation_id: "org-id", organisation_name: "Waibly", indexation_error: "<script>unsafe()</script>" },
    ],
  });
  const { container } = render(<IndexationErrors token="token" />);
  expect(await screen.findByText("Organisation : Waibly")).toBeInTheDocument();
  expect(screen.getByText("Corpus commun")).toBeInTheDocument();
  expect(screen.getByText("<script>unsafe()</script>")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("#indexation-errors")).not.toBeNull();
});

test("a failed request does not claim there are no errors", async () => {
  jest.mocked(apiFetch).mockRejectedValueOnce(new Error("network"));
  render(<IndexationErrors token="token" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Impossible d’actualiser");
  expect(screen.queryByText("Aucun document en erreur d’indexation.")).not.toBeInTheDocument();
});
