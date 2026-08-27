import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LinkedInPostDialog } from "@/components/chat/linkedin-post-dialog";
import { generateLinkedInPost } from "@/lib/chat-api";

jest.mock("@/lib/chat-api", () => ({
  generateLinkedInPost: jest.fn(),
}));

const mockGenerateLinkedInPost = generateLinkedInPost as jest.MockedFunction<
  typeof generateLinkedInPost
>;

describe("LinkedInPostDialog", () => {
  const writeText = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  it("garde le bouton en pied de fenêtre pendant le chargement", async () => {
    mockGenerateLinkedInPost.mockReturnValue(new Promise(() => undefined));

    render(
      <LinkedInPostDialog
        messageId="message-loading"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    const loadingStatus = await screen.findByRole("status");
    expect(loadingStatus).toHaveClass("min-h-0", "flex-1");

    const copyButton = screen.getByRole("button", { name: "Copier le post" });
    expect(copyButton).toBeDisabled();
    expect(copyButton.closest('[data-slot="dialog-footer"]')).toHaveClass(
      "mt-auto",
      "shrink-0"
    );
  });

  it("affiche et copie exactement le post brut puis le garde en cache", async () => {
    const raw =
      "  Accroche conservée\n\nCorps.\n\nSources :\n• Code du travail, art. L.1234-1\n\nVotre avis ?  ";
    mockGenerateLinkedInPost.mockResolvedValue({
      content: raw,
      character_count: raw.length,
      references: ["Code du travail, art. L.1234-1"],
      warnings: ["Avertissement visible sans modification."],
    });

    const { rerender } = render(
      <LinkedInPostDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    const textArea = await screen.findByRole("textbox", {
      name: "Post LinkedIn généré",
    });
    expect(screen.getByRole("dialog")).toHaveClass("h-[92dvh]");
    expect(textArea).toHaveValue(raw);
    expect(
      screen.getByText("Avertissement visible sans modification.")
    ).toBeInTheDocument();
    expect(
      screen.getByText(`${raw.length} / 3 000 caractères`)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Copier le post" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(raw));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Post copié" })
      ).toBeInTheDocument()
    );

    rerender(
      <LinkedInPostDialog
        messageId="message-1"
        token="token-admin"
        open={false}
        onOpenChange={jest.fn()}
      />
    );
    rerender(
      <LinkedInPostDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    expect(
      screen.getByRole("textbox", { name: "Post LinkedIn généré" })
    ).toHaveValue(raw);
    expect(mockGenerateLinkedInPost).toHaveBeenCalledTimes(1);
  });

  it("affiche l'erreur technique et permet de réessayer", async () => {
    mockGenerateLinkedInPost
      .mockRejectedValueOnce(new Error("Service temporairement indisponible"))
      .mockResolvedValueOnce({
        content: "Post généré au second essai",
        character_count: 28,
        references: [],
        warnings: [],
      });

    render(
      <LinkedInPostDialog
        messageId="message-2"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    expect(
      await screen.findByText("Service temporairement indisponible")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));

    expect(
      await screen.findByDisplayValue("Post généré au second essai")
    ).toBeInTheDocument();
    expect(mockGenerateLinkedInPost).toHaveBeenCalledTimes(2);
  });
});
