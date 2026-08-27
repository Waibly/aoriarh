import { render, screen } from "@testing-library/react";

import { ChatMarkdownTable } from "@/components/chat/chat-markdown-table";

describe("ChatMarkdownTable", () => {
  it("rend un tableau sémantique dans un conteneur responsive charté", () => {
    const { container } = render(
      <ChatMarkdownTable>
        <thead>
          <tr>
            <th>Ancienneté</th>
            <th>Préavis</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Moins de deux ans</td>
            <td>Un mois</td>
          </tr>
        </tbody>
      </ChatMarkdownTable>
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("[data-chat-table]")).toBeInTheDocument();
    expect(screen.getByText("Préavis")).toBeInTheDocument();
  });
});
