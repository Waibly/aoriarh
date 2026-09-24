import { act, render, screen } from "@testing-library/react";
import { MessageList } from "@/components/chat/message-list";

jest.mock("@/components/chat/message-bubble", () => ({
  MessageBubble: () => null,
}));
jest.mock("@/components/chat/streaming-bubble", () => ({
  StreamingBubble: ({ content }: { content: string }) => <p>{content}</p>,
}));

beforeEach(() => {
  jest.useFakeTimers();
  Element.prototype.scrollTo = jest.fn();
});
afterEach(() => jest.useRealTimers());

test("shows real stages without resetting total elapsed time or inventing progress", () => {
  const props = { messages: [], isStreaming: true };
  const { rerender, unmount } = render(
    <MessageList
      {...props}
      streamingStatus="Prise en compte de votre situation…"
    />
  );
  act(() => jest.advanceTimersByTime(21000));
  expect(screen.getByLabelText("Temps écoulé")).toHaveTextContent("21 s");
  expect(screen.getByText(/Cette étape est toujours en cours/)).toBeVisible();
  rerender(
    <MessageList
      {...props}
      streamingStatus="Recherche des références utiles…"
    />
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Recherche des références utiles…"
  );
  expect(
    screen.queryByText(/Cette étape est toujours en cours/)
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Temps écoulé")).toHaveTextContent("21 s");
  rerender(<MessageList {...props} streamingContent="Réponse originale" />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("Réponse originale")).toBeVisible();
  unmount();
  expect(jest.getTimerCount()).toBe(0);
});
