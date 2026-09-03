import { render, screen, within } from "@testing-library/react";
import { useSession } from "next-auth/react";
import { MessageBubble } from "@/components/chat/message-bubble";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Message } from "@/types/api";

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => null }));
jest.mock("rehype-sanitize", () => ({ __esModule: true, default: () => null }));
jest.mock("@/lib/legal-refs/rehype-legal-refs", () => ({
  rehypeLegalRefs: () => null,
}));

jest.mock("next-auth/react", () => ({
  useSession: jest.fn(),
}));

jest.mock("@/lib/chat-api", () => ({
  downloadFiche: jest.fn(),
  generateLinkedInPost: jest.fn(),
  generateSocialMedia: jest.fn(),
  getSourceFullContent: jest.fn(),
  renderSocialMediaHtml: jest.fn(),
}));

const mockUseSession = useSession as jest.Mock;

const message: Message = {
  id: "message-assistant-1",
  conversation_id: "conversation-1",
  role: "assistant",
  content: "Réponse juridique affichée sans modification.",
  sources: [],
  feedback: null,
  feedback_comment: null,
  fiche_eligible: true,
  created_at: "2026-08-25T12:00:00Z",
};

function renderMessage(value: Message = message) {
  return render(
    <TooltipProvider>
      <MessageBubble message={value} />
    </TooltipProvider>
  );
}

describe("bouton LinkedIn de MessageBubble", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("place les deux outils admin dans un encart séparé de la fiche", () => {
    mockUseSession.mockReturnValue({
      data: {
        access_token: "token-admin",
        user: { role: "admin" },
      },
    });

    renderMessage();

    expect(
      screen.getByRole("button", { name: "Créer une fiche pratique" })
    ).toBeInTheDocument();

    const publicationTools = screen.getByRole("group", {
      name: "Outils de publication administrateur",
    });
    expect(publicationTools).toHaveClass(
      "w-full",
      "justify-end",
      "bg-primary/5"
    );
    expect(
      within(publicationTools).getByRole("button", {
        name: "Générer le post LinkedIn",
      })
    ).toBeInTheDocument();
    expect(
      within(publicationTools).getByRole("button", {
        name: "Générer un post + carrousel LinkedIn",
      })
    ).toBeInTheDocument();
    expect(
      within(publicationTools).queryByRole("button", {
        name: "Créer une fiche pratique",
      })
    ).not.toBeInTheDocument();
  });

  it("est absent pour un compte non administrateur", () => {
    mockUseSession.mockReturnValue({
      data: {
        access_token: "token-manager",
        user: { role: "manager" },
      },
    });

    renderMessage();

    expect(
      screen.queryByRole("button", { name: "Générer le post LinkedIn" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Générer un post + carrousel LinkedIn",
      })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", {
        name: "Outils de publication administrateur",
      })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Créer une fiche pratique" })
    ).toBeInTheDocument();
  });

  it("reste absent pour une réponse de sécurité", () => {
    mockUseSession.mockReturnValue({
      data: {
        access_token: "token-admin",
        user: { role: "admin" },
      },
    });

    renderMessage({ ...message, fiche_eligible: false });

    expect(
      screen.queryByRole("button", { name: "Générer le post LinkedIn" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Générer un post + carrousel LinkedIn",
      })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Créer une fiche pratique" })
    ).not.toBeInTheDocument();
  });
});
