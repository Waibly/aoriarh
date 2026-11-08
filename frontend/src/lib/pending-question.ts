// Question transmise depuis le site (outils gratuits) jusqu'au premier écran du
// chat, à travers l'inscription ou la connexion (y compris le retour Google).
// La question est seulement préremplie dans la zone de saisie : l'utilisateur
// la relit et l'envoie lui-même. Aucune requête n'est lancée automatiquement.

const STORAGE_KEY = "aoria_pending_question";
const MAX_LENGTH = 1000;
const TTL_MS = 2 * 60 * 60 * 1000;

interface StoredQuestion {
  text: string;
  storedAt: number;
}

export function storePendingQuestion(raw: string | null | undefined): void {
  if (typeof window === "undefined" || !raw) return;
  const text = raw.slice(0, MAX_LENGTH).trim();
  if (!text) return;
  try {
    const value: StoredQuestion = { text, storedAt: Date.now() };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Stockage indisponible (navigation privée stricte) : la question est perdue, sans erreur.
  }
}

export function peekPendingQuestion(now: number = Date.now()): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredQuestion>;
    if (
      typeof parsed.text !== "string" ||
      typeof parsed.storedAt !== "number" ||
      now - parsed.storedAt > TTL_MS ||
      now < parsed.storedAt
    ) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    const text = parsed.text.slice(0, MAX_LENGTH).trim();
    return text || null;
  } catch {
    return null;
  }
}

export function clearPendingQuestion(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignoré
  }
}
