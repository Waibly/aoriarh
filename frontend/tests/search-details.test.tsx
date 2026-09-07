import { render } from "@testing-library/react";
import { SearchDetailsPanel } from "@/components/chat/search-details";

test("does not render internal search details", () => {
  const raw = '  {"standalone_question": "incomplet"\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: raw,
    warnings: ["Recherche de secours utilisée."],
  }} />);
  expect(container.firstChild).toBeNull();
  expect(container).not.toHaveTextContent(raw);
  expect(container).not.toHaveTextContent("Recherche de secours utilisée.");
});

test("does not render the classifier either", () => {
  const raw = ' {"intent":"legal_question"}\n';
  const { container } = render(<SearchDetailsPanel details={{
    raw_response: null, router_raw_response: raw, warnings: [],
  }} />);
  expect(container.firstChild).toBeNull();
  expect(container).not.toHaveTextContent(raw);
});
