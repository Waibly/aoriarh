import {
  act,
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

afterEach(() => {
  jest.useRealTimers();
});

it("rotates the idea every ten seconds without changing the draft or sending a request", () => {
  jest.useFakeTimers();
  const onSend = jest.fn();
  render(<WelcomeScreen onSend={onSend} onAttach={jest.fn()} />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Mon travail en cours" },
  });
  const ideas = screen.getByRole("complementary");
  expect(ideas).toHaveTextContent("Analysez aussi vos documents");
  act(() => jest.advanceTimersByTime(9_999));
  expect(ideas).toHaveTextContent("Analysez aussi vos documents");
  act(() => jest.advanceTimersByTime(1));
  expect(ideas).toHaveTextContent("Comparez deux versions");
  act(() => jest.advanceTimersByTime(10_000));
  expect(ideas).toHaveTextContent("Préparez un écrit");
  expect(screen.getByRole("textbox")).toHaveValue("Mon travail en cours");
  expect(onSend).not.toHaveBeenCalled();
});

it("lets the user pause and resume automatic ideas", () => {
  jest.useFakeTimers();
  render(<WelcomeScreen onSend={jest.fn()} onAttach={jest.fn()} />);
  const ideas = screen.getByRole("complementary");
  fireEvent.click(
    screen.getByRole("button", { name: "Mettre en pause les idées" })
  );
  act(() => jest.advanceTimersByTime(30_000));
  expect(ideas).toHaveTextContent("Analysez aussi vos documents");
  fireEvent.click(
    screen.getByRole("button", { name: "Reprendre le défilement des idées" })
  );
  act(() => jest.advanceTimersByTime(10_000));
  expect(ideas).toHaveTextContent("Comparez deux versions");
});

it("suspends rotation while the user reads or focuses the idea", () => {
  jest.useFakeTimers();
  render(<WelcomeScreen onSend={jest.fn()} onAttach={jest.fn()} />);
  const ideas = screen.getByRole("complementary");
  fireEvent.mouseEnter(ideas);
  act(() => jest.advanceTimersByTime(20_000));
  expect(ideas).toHaveTextContent("Analysez aussi vos documents");
  fireEvent.mouseLeave(ideas);
  const next = within(ideas).getByRole("button", { name: "Autre conseil" });
  fireEvent.focus(next);
  act(() => jest.advanceTimersByTime(20_000));
  expect(ideas).toHaveTextContent("Analysez aussi vos documents");
  fireEvent.blur(next, { relatedTarget: document.body });
  act(() => jest.advanceTimersByTime(10_000));
  expect(ideas).toHaveTextContent("Comparez deux versions");
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
  "shows the input, rotating ideas, then four separate cards for %s",
  (_profile, title) => {
    mockProfile = _profile;
    const onSend = jest.fn();
    render(<WelcomeScreen onSend={onSend} onAttach={jest.fn()} />);
    const suggestions = screen.getByRole("group", {
      name: "Des idées pour votre quotidien",
    });
    expect(within(suggestions).getAllByRole("button")).toHaveLength(4);
    const composer = screen
      .getByRole("textbox")
      .closest('[data-slot="chat-input"]')!;
    const ideas = screen.getByRole("complementary", {
      name: "Idées et conseils",
    });
    expect(composer).not.toContainElement(suggestions);
    expect(
      composer.compareDocumentPosition(ideas) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      ideas.compareDocumentPosition(suggestions) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
    fireEvent.click(within(suggestions).getByRole("button", { name: title }));
    expect(screen.getByRole("textbox")).not.toHaveValue("");
    expect(screen.getByRole("textbox")).toHaveFocus();
    expect(onSend).not.toHaveBeenCalled();
  }
);

it("keeps the draft when changing profiles and can undo an example replacement", async () => {
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
  expect(draft).toMatch(/^Mon client envisage un CDD/);
  expect(draft).not.toContain("Mes faits à conserver");
  expect(onSend).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", {
      name: "Annuler le remplacement de la demande",
    })
  );
  expect(screen.getByRole("textbox")).toHaveValue("Mes faits à conserver");
  fireEvent.click(
    screen.getByRole("button", { name: "Conseiller un client sur un CDD" })
  );
  fireEvent.click(screen.getByRole("button", { name: "Envoyer le message" }));
  expect(onSend).toHaveBeenCalledTimes(1);
  expect(onSend).toHaveBeenCalledWith(draft);
  await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
});

it("replaces the selected request on repeated and successive clicks instead of accumulating examples", () => {
  mockProfile = "drh";
  const onSend = jest.fn();
  render(<WelcomeScreen onSend={onSend} onAttach={jest.fn()} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Faire évoluer les horaires" })
  );
  const first = (screen.getByRole("textbox") as HTMLTextAreaElement).value;
  fireEvent.click(
    screen.getByRole("button", { name: "Comparer accord et contrat" })
  );
  const second = (screen.getByRole("textbox") as HTMLTextAreaElement).value;
  expect(second).toMatch(/^Compare les dispositions/);
  expect(second).not.toContain(first);
  fireEvent.click(
    screen.getByRole("button", { name: "Comparer accord et contrat" })
  );
  expect(screen.getByRole("textbox")).toHaveValue(second);
  fireEvent.click(
    screen.getByRole("button", { name: "Préparer une note à la direction" })
  );
  expect(
    (screen.getByRole("textbox") as HTMLTextAreaElement).value
  ).not.toContain(second);
  expect(onSend).not.toHaveBeenCalled();
});

it("recovers an edited draft when undoing a new example selection", () => {
  render(<WelcomeScreen onSend={jest.fn()} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Préparer un email ou un courrier" })
  );
  const edited = "  Ma demande personnalisée\navec mes faits et mes dates.  ";
  fireEvent.change(screen.getByRole("textbox"), { target: { value: edited } });
  expect(
    screen.queryByRole("button", {
      name: "Annuler le remplacement de la demande",
    })
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Comprendre une règle de congé" })
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Annuler le remplacement de la demande",
    })
  );
  expect(screen.getByRole("textbox")).toHaveValue(edited);
  expect(screen.getByRole("textbox")).toHaveFocus();
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
  fireEvent.click(screen.getByRole("button", { name: "Masquer les idées" }));
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  view.unmount();
  render(<WelcomeScreen onSend={jest.fn()} />);
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Afficher les idées" }));
  expect(screen.getByRole("complementary")).toBeVisible();
});

it("can advance ideas manually and invoke attachment/library actions", () => {
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
