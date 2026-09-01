import { render, screen } from "@testing-library/react";
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

  it("est visible pour un admin à côté de la fiche pratique", () => {
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
    expect(
      screen.getByRole("button", { name: "Générer le post LinkedIn" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Générer un média" })
    ).toBeInTheDocument();
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
      screen.queryByRole("button", { name: "Générer un média" })
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
      screen.queryByRole("button", { name: "Générer un média" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Créer une fiche pratique" })
    ).not.toBeInTheDocument();
  });
});
