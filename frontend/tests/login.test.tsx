import { render, screen } from "@testing-library/react";
import LoginPage from "@/app/(auth)/login/page";

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

describe("LoginPage", () => {
  it("renders the login form with email and password fields", () => {
    render(<LoginPage />);
    expect(screen.getByText("Connexion")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Mot de passe")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Se connecter" })
    ).toBeInTheDocument();
  });

  it("renders a link to the register page", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: "Créer un compte" });
    expect(link).toHaveAttribute("href", "/register");
  });
});
