import { render, screen } from "@testing-library/react";
import RegisterPage from "@/app/(auth)/register/page";

jest.mock("next-auth/react", () => ({
  signIn: jest.fn(),
  SessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    refresh: jest.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("RegisterPage", () => {
  it("renders the registration form with all fields", () => {
    render(<RegisterPage />);
    expect(screen.getByText("Créer un compte")).toBeInTheDocument();
    expect(screen.getByLabelText("Nom complet")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Confirmer le mot de passe")
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Créer mon compte" })
    ).toBeInTheDocument();
  });

  it("renders a link to the login page", () => {
    render(<RegisterPage />);
    const link = screen.getByRole("link", { name: "Se connecter" });
    expect(link).toHaveAttribute("href", "/login");
  });
});
