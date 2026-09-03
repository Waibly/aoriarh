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

  beforeEach(() => {
    jest.clearAllMocks();
    mockDownloadPdf.mockResolvedValue(
      new Blob(["pdf"], { type: "application/pdf" })
    );
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: jest.fn(() => "blob:pdf"),
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: jest.fn(),
    });
    jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation();
    mockGenerate.mockResolvedValue({
      raw_content: raw,
      html: generatedHtml,
      images: [
        {
          filename: "aoria-media-01.png",
          content_base64: "aW1hZ2U=",
        },
      ],
      references: [],
      warnings: ["Avertissement non bloquant"],
      render_error: null,
    });
  });

  it("affiche la sortie brute exacte et le HTML éditable", async () => {
    render(
      <SocialMediaDialog
        messageId="message-1"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    expect(
      await screen.findByText("Avertissement non bloquant")
    ).toBeInTheDocument();

    fireEvent.mouseDown(
      screen.getByRole("tab", { name: "Sortie brute du LLM" }),
      {
        button: 0,
        ctrlKey: false,
      }
    );
    expect(
      screen.getByRole("textbox", { name: "Sortie brute du LLM" })
    ).toHaveValue(raw);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Modifier le HTML" }), {
      button: 0,
      ctrlKey: false,
    });
    expect(screen.getByRole("textbox", { name: "HTML du média" })).toHaveValue(
      generatedHtml
    );
    expect(mockGenerate).toHaveBeenCalledTimes(1);
  });

  it("transmet le HTML édité exactement au moteur PNG", async () => {
    mockRender.mockResolvedValue({
      images: [
        {
          filename: "aoria-media-01.png",
          content_base64: "bm91dmVsbGUtaW1hZ2U=",
        },
      ],
    });
    const edited = "  <!doctype html>\n<body>Version éditée</body>  ";

    render(
      <SocialMediaDialog
        messageId="message-2"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    await screen.findByText("Avertissement non bloquant");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Modifier le HTML" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.change(screen.getByRole("textbox", { name: "HTML du média" }), {
      target: { value: edited },
    });

    expect(screen.getByTitle("Aperçu HTML en direct")).toHaveAttribute(
      "srcdoc",
      edited
    );
    expect(
      screen.getByText(/L’aperçu ci-dessous est à jour/)
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Générer les PNG pour l’export" })
    );

    await waitFor(() =>
      expect(mockRender).toHaveBeenCalledWith(
        "message-2",
        edited,
        "token-admin"
      )
    );
    await waitFor(() =>
      expect(
        screen.queryByText(/L’aperçu ci-dessous est à jour/)
      ).not.toBeInTheDocument()
    );
  });

  it("conserve le HTML quand le rendu PNG échoue", async () => {
    mockRender.mockRejectedValue(new Error("Rendu impossible, HTML conservé"));

    render(
      <SocialMediaDialog
        messageId="message-3"
        token="token-admin"
        open
        onOpenChange={jest.fn()}
      />
    );

    await screen.findByText("Avertissement non bloquant");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Modifier le HTML" }), {
      button: 0,
      ctrlKey: false,
    });
    const editor = screen.getByRole("textbox", { name: "HTML du média" });
    fireEvent.change(editor, {
      target: { value: "<body>HTML à conserver</body>" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Générer les PNG pour l’export" })
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
      />
    );

    await screen.findByText("Avertissement non bloquant");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Modifier le HTML" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.change(screen.getByRole("textbox", { name: "HTML du média" }), {
      target: { value: edited },
    });
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
});
