import {
  clearPendingQuestion,
  peekPendingQuestion,
  storePendingQuestion,
} from "@/lib/pending-question";

beforeEach(() => localStorage.clear());

it("conserve une question transmise par le site, tronquée à 1 000 caractères", () => {
  storePendingQuestion("  Entreprise de 12 salariés. Que faire après un accident ?  ");
  expect(peekPendingQuestion()).toBe("Entreprise de 12 salariés. Que faire après un accident ?");
  storePendingQuestion("a".repeat(1500));
  expect(peekPendingQuestion()).toHaveLength(1000);
});

it("ignore les valeurs vides et ne remplace pas une question par rien", () => {
  storePendingQuestion("Question valable");
  storePendingQuestion(null);
  storePendingQuestion("   ");
  expect(peekPendingQuestion()).toBe("Question valable");
});

it("expire après deux heures et se supprime", () => {
  storePendingQuestion("Question ancienne");
  const storedAt = JSON.parse(localStorage.getItem("aoria_pending_question")!).storedAt;
  expect(peekPendingQuestion(storedAt + 2 * 60 * 60 * 1000 + 1)).toBeNull();
  expect(localStorage.getItem("aoria_pending_question")).toBeNull();
});

it("rejette un contenu stocké invalide et se vide sur demande", () => {
  localStorage.setItem("aoria_pending_question", "pas du json");
  expect(peekPendingQuestion()).toBeNull();
  storePendingQuestion("À effacer");
  clearPendingQuestion();
  expect(peekPendingQuestion()).toBeNull();
});
