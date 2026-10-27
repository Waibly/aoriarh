import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { WelcomeScreen } from "@/components/chat/welcome-screen";

let mockProfile: string | null = null;
jest.mock("@/lib/org-context", () => ({
  useOrg: () => ({ profilMetier: mockProfile }),
}));

beforeEach(() => {
  mockProfile = null;
  localStorage.clear();
});

it.each([
  ["drh", "Faire évoluer les horaires"],
  ["charge_rh", "Répondre à une demande de congé"],
  ["dirigeant", "Réagir à une absence inexpliquée"],
  ["elu_cse", "Comprendre les heures de délégation"],
  ["juriste", "Approfondir une question juridique"],
  ["consultant_rh", "Faire évoluer le télétravail"],
  ["comptable_paie", "Examiner le maintien de salaire"],
  ["expert_comptable", "Conseiller un client sur un CDD"],
])(
  "offers four compact suggestions for %s and prepares editable input",
  (_profile, title) => {
    mockProfile = _profile;
    const onSend = jest.fn();
    render(<WelcomeScreen onSend={onSend} onAttach={jest.fn()} />);
    const suggestions = screen.getByRole("group", {
      name: "Des idées pour votre quotidien",
    });
    expect(within(suggestions).getAllByRole("button")).toHaveLength(4);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
    fireEvent.click(within(suggestions).getByRole("button", { name: title }));
    expect(screen.getByRole("textbox")).not.toHaveValue("");
    expect(screen.getByRole("textbox")).toHaveFocus();
    expect(onSend).not.toHaveBeenCalled();
  }
);

it("updates examples when the profile changes without replacing an existing draft", async () => {
  const onSend = jest.fn();
  const view = render(<WelcomeScreen onSend={onSend} />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Mes faits à conserver" },
  });
  mockProfile = "expert_comptable";
  view.rerender(<WelcomeScreen onSend={onSend} />);
  expect(screen.getByRole("textbox")).toHaveValue("Mes faits à conserver");
  fireEvent.click(
    screen.getByRole("button", { name: "Conseiller un client sur un CDD" })
  );
  const draft = (screen.getByRole("textbox") as HTMLTextAreaElement).value;
  expect(draft).toMatch(/^Mes faits à conserver\n\nMon client envisage un CDD/);
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Envoyer le message" }));
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(onSend).toHaveBeenCalledWith(draft);
  await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
});

it("filters the on-demand catalogue and returns focus to the editable request", async () => {
  const onSend = jest.fn();
  render(<WelcomeScreen onSend={onSend} onAttach={jest.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Voir les exemples" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Rédiger" }));
  expect(
    within(dialog).queryByRole("button", { name: /Comparer deux documents/ })
  ).not.toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: /Préparer une trame d’entretien/,
    })
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
  await waitFor(() =>
    expect(
      (screen.getByRole("textbox") as HTMLTextAreaElement).value
    ).toContain("trame d’entretien")
  );
  expect(screen.getByRole("textbox")).toHaveFocus();
  expect(onSend).not.toHaveBeenCalled();
});

it("opens attachment choices for documentary tasks without sending a request", () => {
  const onSend = jest.fn();
  const onAttach = jest.fn();
  render(<WelcomeScreen onSend={onSend} onAttach={onAttach} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Résumer un document RH" })
  );
  expect(
    screen.getByRole("button", { name: /Importer un fichier/ })
  ).toBeVisible();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain(
    "Résume le document"
  );
  expect(onSend).not.toHaveBeenCalled();
  expect(onAttach).not.toHaveBeenCalled();
});

it("keeps document controls closed when a piece is already selected", () => {
  render(
    <WelcomeScreen
      onSend={jest.fn()}
      onAttach={jest.fn()}
      attachments={[
        {
          document_id: "doc",
          extraction_id: "version",
          name: "contrat.txt",
        },
      ]}
    />
  );
  expect(screen.getByRole("complementary")).toHaveTextContent(
    "Comparez deux versions"
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Résumer un document RH" })
  );
  expect(
    screen.queryByRole("button", { name: /Importer un fichier/ })
  ).not.toBeInTheDocument();
});

it.each(["unknown", "juriste"])(
  "offers distinct usable examples without attachments for profile %s",
  (profile) => {
    mockProfile = profile;
    render(<WelcomeScreen onSend={jest.fn()} />);
    const suggestions = screen.getByRole("group", {
      name: "Des idées pour votre quotidien",
    });
    expect(within(suggestions).getAllByRole("button")).toHaveLength(4);
    expect(
      new Set(
        within(suggestions)
          .getAllByRole("button")
          .map((button) => button.textContent)
      ).size
    ).toBe(4);
    expect(
      screen.queryByRole("button", { name: "Résumer un document RH" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Voir les exemples" }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).queryByRole("button", { name: /Comparer deux documents/ })
    ).not.toBeInTheDocument();
  }
);

it("remembers tip dismissal and lets the user restore it", () => {
  const view = render(<WelcomeScreen onSend={jest.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Masquer les conseils" }));
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  view.unmount();
  render(<WelcomeScreen onSend={jest.fn()} />);
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Afficher un conseil" }));
  expect(screen.getByRole("complementary")).toBeVisible();
});

it("advances tips only on request and invokes the real attachment/library actions", () => {
  const onBrowse = jest.fn();
  const onSend = jest.fn();
  render(
    <WelcomeScreen onSend={onSend} onAttach={jest.fn()} onBrowse={onBrowse} />
  );
  const tip = screen.getByRole("complementary");
  fireEvent.click(within(tip).getByRole("button", { name: "Autre conseil" }));
  expect(tip).toHaveTextContent("Comparez deux versions");
  fireEvent.click(
    within(tip).getByRole("button", { name: "Préparer une comparaison" })
  );
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain(
    "Compare les deux versions"
  );
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  for (let i = 0; i < 6; i++)
    fireEvent.click(within(tip).getByRole("button", { name: "Autre conseil" }));
  fireEvent.click(
    within(tip).getByRole("button", { name: "Choisir un document" })
  );
  expect(onBrowse).toHaveBeenCalledTimes(1);
});

it("disables suggestion and tip actions while a request is unavailable", () => {
  mockProfile = "expert_comptable";
  const onSend = jest.fn();
  const onBrowse = jest.fn();
  render(
    <WelcomeScreen
      onSend={onSend}
      onAttach={jest.fn()}
      onBrowse={onBrowse}
      disabled
    />
  );
  const suggestions = screen.getByRole("group", {
    name: "Des idées pour votre quotidien",
  });
  for (const button of within(suggestions).getAllByRole("button")) {
    expect(button).toBeDisabled();
    fireEvent.click(button);
  }
  expect(
    screen.getByRole("button", { name: "Ajouter une pièce" })
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Voir les exemples" })
  ).toBeDisabled();
  expect(screen.getByRole("textbox")).toHaveValue("");
  expect(onSend).not.toHaveBeenCalled();
  expect(onBrowse).not.toHaveBeenCalled();
});
