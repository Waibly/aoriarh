import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { XPostDialog } from "@/components/chat/x-post-dialog";
import { generateXPost, renderSocialMediaHtml } from "@/lib/chat-api";

jest.mock("@/lib/chat-api", () => ({
  generateXPost: jest.fn(),
  renderSocialMediaHtml: jest.fn(),
}));

const mockGenerateXPost = generateXPost as jest.MockedFunction<
  typeof generateXPost
>;
const mockRender = renderSocialMediaHtml as jest.MockedFunction<
  typeof renderSocialMediaHtml
>;

describe("XPostDialog", () => {
  const writeText = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    mockRender.mockResolvedValue({
      images: [{ filename: "aoria-media-01.png", content_base64: "cG5n" }],
    });
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:x-visual"),
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation();
  });

  it("propose les formats gratuits et recommande un fil de trois posts", () => {
    render(
      <XPostDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    expect(
      screen.getByRole("combobox", { name: "Format de publication X" })
    ).toHaveTextContent("Fil de 3 posts (recommandé)");
    expect(
      screen.getByText("3 posts · 280 caractères chacun · Tous les comptes")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/compatible avec votre compte X gratuit/)
    ).toBeInTheDocument();
    expect(mockGenerateXPost).not.toHaveBeenCalled();
  });

  it("génère, affiche et copie exactement le fil brut", async () => {
    const raw = "  1/3 Hook.\n\n2/3 Règle.\n\n3/3 Source.  ";
    const visualRaw =
      '  <main class="x-card"><section class="x-visual"><h1>Titre</h1></section></main>  ';
    const visualHtml = `<!doctype html><body>${visualRaw}</body>`;
    mockGenerateXPost.mockResolvedValue({
      content: raw,
      character_count: raw.length,
      format: "thread",
      references: [],
      warnings: ["Avertissement technique visible."],
      visual_raw_content: visualRaw,
      visual_html: visualHtml,
      visual_warnings: ["Avertissement visuel visible."],
      visual_error: null,
    });

    render(
      <XPostDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Générer" }));

    expect(
      await screen.findByRole("textbox", { name: "Publication X générée" })
    ).toHaveValue(raw);
    expect(
      screen.getByText("Avertissement technique visible.")
    ).toBeInTheDocument();
    expect(
      screen.getByText("Avertissement visuel visible.")
    ).toBeInTheDocument();
    expect(await screen.findByAltText("Page 1 sur 1")).toHaveAttribute(
      "src",
      "data:image/png;base64,cG5n"
    );
    expect(mockRender).toHaveBeenCalledWith(
      "message-1",
      visualHtml,
      "token-admin"
    );
    expect(mockGenerateXPost).toHaveBeenCalledWith(
      "message-1",
      "token-admin",
      "thread"
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Copier la publication" })
    );
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(raw));

    fireEvent.click(screen.getByText("Voir la sortie brute du visuel"));
    expect(
      screen.getByRole("textbox", { name: "Sortie brute du visuel X" })
    ).toHaveValue(visualRaw);

    fireEvent.click(screen.getByRole("button", { name: "Télécharger le PNG" }));
    await waitFor(() =>
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    );
  });
});
