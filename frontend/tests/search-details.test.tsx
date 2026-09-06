import { render, screen } from "@testing-library/react";
import { SearchDetailsPanel } from "@/components/chat/search-details";

test("keeps nonempty invalid output verbatim beside its warning", () => {
  const raw = '  {"standalone_question": "incomplet"\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: raw,
    warnings: ["Recherche de secours utilisée."],
  }} />);
  expect(container.querySelector("pre")?.textContent).toBe(raw);
  expect(screen.getByRole("status")).toHaveTextContent("Recherche de secours utilisée.");
  expect(container.querySelector("details")).toHaveAttribute("open");
});

test("displays the classifier even when there is no planner output", () => {
  const raw = ' {"intent":"legal_question"}\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: null, router_raw_response: raw, warnings: [],
  }} />);
  expect(container.querySelector("pre")?.textContent).toBe(raw);
});
