import { render, screen } from "@testing-library/react";
import { SearchDetailsPanel } from "@/components/chat/search-details";

test("does not expose raw planner output beside its warning", () => {
  const raw = '  {"standalone_question": "incomplet"\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: raw,
    warnings: ["Recherche de secours utilisée."],
  }} />);
  expect(container.querySelector("pre")).toBeNull();
  expect(container).not.toHaveTextContent(raw);
  expect(screen.getByRole("status")).toHaveTextContent("Recherche de secours utilisée.");
  expect(container.querySelector("details")).toHaveAttribute("open");
});

test("does not expose the classifier when there is no user-facing warning", () => {
  const raw = ' {"intent":"legal_question"}\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: null, router_raw_response: raw, warnings: [],
  }} />);
  expect(container.firstChild).toBeNull();
  expect(container).not.toHaveTextContent(raw);
});
