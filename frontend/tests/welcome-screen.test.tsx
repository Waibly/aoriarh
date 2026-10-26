import { fireEvent, render, screen } from "@testing-library/react";
import { WelcomeScreen } from "@/components/chat/welcome-screen";

let mockProfile: string | null = null;
jest.mock("@/lib/org-context", () => ({
  useOrg: () => ({ profilMetier: mockProfile }),
}));
jest.mock("@/components/chat/chat-input", () => ({
  ChatInput: () => <div />,
}));

beforeEach(() => {
  mockProfile = null;
});

it("updates suggestions when the personal profile changes and sends the exact chosen question", () => {
  const onSend = jest.fn();
  const view = render(<WelcomeScreen onSend={onSend} />);
  expect(
    screen.getByRole("button", {
      name: /heures supplémentaires non autorisées/,
    })
  ).toBeEnabled();

  mockProfile = "comptable_paie";
  view.rerender(<WelcomeScreen onSend={onSend} />);
  const payroll = screen.getByRole("button", { name: /Arrêt maladie/ });
  fireEvent.click(payroll);
  expect(onSend).toHaveBeenLastCalledWith(payroll.textContent);

  mockProfile = "expert_comptable";
  view.rerender(<WelcomeScreen onSend={onSend} />);
  const client = screen.getByRole("button", {
    name: /Mon client prépare la paie/,
  });
  fireEvent.click(client);
  expect(onSend).toHaveBeenLastCalledWith(client.textContent);
  expect(
    screen.queryByRole("button", { name: /^Arrêt maladie/ })
  ).not.toBeInTheDocument();
});

it("keeps suggestions disabled while sending is unavailable", () => {
  mockProfile = "expert_comptable";
  const onSend = jest.fn();
  render(<WelcomeScreen onSend={onSend} disabled />);
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
    fireEvent.click(button);
  }
  expect(onSend).not.toHaveBeenCalled();
});
