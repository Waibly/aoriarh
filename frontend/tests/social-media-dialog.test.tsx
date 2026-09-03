import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SocialMediaDialog } from "@/components/chat/social-media-dialog";
import {
  downloadSocialMediaPdf,
  generateSocialMedia,
  renderSocialMediaHtml,
} from "@/lib/chat-api";

jest.mock("@/lib/chat-api", () => ({
  downloadSocialMediaPdf: jest.fn(),
  generateSocialMedia: jest.fn(),
  renderSocialMediaHtml: jest.fn(),
}));

const mockGenerate = generateSocialMedia as jest.MockedFunction<
  typeof generateSocialMedia
>;
const mockRender = renderSocialMediaHtml as jest.MockedFunction<
  typeof renderSocialMediaHtml
>;
const mockDownloadPdf = downloadSocialMediaPdf as jest.MockedFunction<
  typeof downloadSocialMediaPdf
>;

describe("SocialMediaDialog", () => {
  const raw =
    '  <main class="carousel"><section class="slide">Texte brut</section></main>  ';
  const generatedHtml = `<!doctype html><body>${raw}</body>`;
  const postContent =
    "Une décision RH peut sembler simple.\n\nCe carrousel montre les points à examiner avant d’agir.\n\nQuelle vigilance guide votre pratique ?";
  const writeText = jest.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    mockDownloadPdf.mockResolvedValue(
      new Blob(["pdf"], { type: "application/pdf" })
    );
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:export"),
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation();
    mockGenerate.mockResolvedValue({
      post: {
        content: postContent,
        character_count: postContent.length,
        references: [],
        warnings: [],
      },
      post_error: null,
      raw_content: raw,
      html: generatedHtml,
      images: [],
      references: [],
      warnings: ["Avertissement non bloquant"],
      render_error: null,
    });
  });

  it("affiche d’abord le post puis l’unique aperçu du carrousel", async () => {
    render(
      <SocialMediaDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="linkedin-carousel"
      />
    );

    const post = await screen.findByRole("textbox", {
      name: "Post LinkedIn du carrousel",
    });
    const preview = screen.getByTitle("Aperçu du carrousel LinkedIn");

    expect(post).toHaveValue(postContent);
    expect(post.compareDocumentPosition(preview)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(post.closest("section")?.parentElement).toBe(
      preview.closest("section")?.parentElement
    );
    expect(post.closest("section")?.parentElement).toHaveClass(
      "lg:grid-cols-[minmax(340px,0.72fr)_minmax(0,1.8fr)]"
    );
    expect(screen.getByRole("dialog")).toHaveClass(
      "w-[96vw]",
      "xl:max-w-[1800px]"
    );
    expect(screen.getAllByTitle("Aperçu du carrousel LinkedIn")).toHaveLength(
      1
    );
    expect(preview).toHaveAttribute("srcdoc", generatedHtml);
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(mockGenerate).toHaveBeenCalledWith("message-1", "token-admin", true);

    fireEvent.click(screen.getByRole("button", { name: "Copier le post" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(postContent));
  });

  it("affiche la sortie brute exacte et actualise l’aperçu pendant l’édition", async () => {
    const edited = "  <!doctype html>\n<body>Version éditée</body>  ";

    render(
      <SocialMediaDialog
        messageId="message-2"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="linkedin-carousel"
      />
    );

    await screen.findByText("Avertissement non bloquant");
    fireEvent.click(screen.getByText("Voir la sortie brute du carrousel"));
    expect(
      screen.getByRole("textbox", { name: "Sortie brute du carrousel" })
    ).toHaveValue(raw);

    fireEvent.click(screen.getByText("Modifier le HTML du carrousel"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "HTML du carrousel" }),
      { target: { value: edited } }
    );

    expect(screen.getByTitle("Aperçu du carrousel LinkedIn")).toHaveAttribute(
      "srcdoc",
      edited
    );
    expect(mockRender).not.toHaveBeenCalled();
  });

  it("génère et télécharge les PNG en une seule action", async () => {
    mockRender.mockResolvedValue({
      images: [
        {
          filename: "aoria-media-01.png",
          content_base64: "bm91dmVsbGUtaW1hZ2U=",
        },
      ],
    });

    render(
      <SocialMediaDialog
        messageId="message-png"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="linkedin-carousel"
      />
    );

    await screen.findByRole("textbox", {
      name: "Post LinkedIn du carrousel",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Télécharger les PNG" })
    );

    await waitFor(() =>
      expect(mockRender).toHaveBeenCalledWith(
        "message-png",
        generatedHtml,
        "token-admin"
      )
    );
    await waitFor(() =>
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled()
    );
  });

  it("conserve le HTML quand l’export PNG échoue", async () => {
    mockRender.mockRejectedValue(new Error("Rendu impossible, HTML conservé"));

    render(
      <SocialMediaDialog
        messageId="message-3"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="linkedin-carousel"
      />
    );

    await screen.findByRole("textbox", {
      name: "Post LinkedIn du carrousel",
    });
    fireEvent.click(screen.getByText("Modifier le HTML du carrousel"));
    const editor = screen.getByRole("textbox", { name: "HTML du carrousel" });
    fireEvent.change(editor, {
      target: { value: "<body>HTML à conserver</body>" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Télécharger les PNG" })
    );

    expect(
      await screen.findByText("Rendu impossible, HTML conservé")
    ).toBeInTheDocument();
    expect(editor).toHaveValue("<body>HTML à conserver</body>");
  });

  it("exporte en PDF LinkedIn le HTML édité exact", async () => {
    const edited = "  <!doctype html>\n<body>Version LinkedIn</body>  ";

    render(
      <SocialMediaDialog
        messageId="message-pdf"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="linkedin-carousel"
      />
    );

    await screen.findByRole("textbox", {
      name: "Post LinkedIn du carrousel",
    });
    fireEvent.click(screen.getByText("Modifier le HTML du carrousel"));
    fireEvent.change(
      screen.getByRole("textbox", { name: "HTML du carrousel" }),
      { target: { value: edited } }
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Télécharger le PDF LinkedIn" })
    );

    await waitFor(() =>
      expect(mockDownloadPdf).toHaveBeenCalledWith(
        "message-pdf",
        edited,
        "token-admin"
      )
    );
  });

  it("conserve le média autonome sans générer de post LinkedIn", async () => {
    mockGenerate.mockResolvedValueOnce({
      post: null,
      post_error: null,
      raw_content: raw,
      html: generatedHtml,
      images: [],
      references: [],
      warnings: [],
      render_error: null,
    });

    render(
      <SocialMediaDialog
        messageId="message-media"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
        variant="media"
      />
    );

    expect(await screen.findByText("Générer un média")).toBeInTheDocument();
    expect(screen.getByTitle("Aperçu du média")).toHaveAttribute(
      "srcdoc",
      generatedHtml
    );
    expect(
      screen.queryByRole("textbox", { name: "Post LinkedIn du carrousel" })
    ).not.toBeInTheDocument();
    expect(mockGenerate).toHaveBeenCalledWith(
      "message-media",
      "token-admin",
      false
    );
  });
});
