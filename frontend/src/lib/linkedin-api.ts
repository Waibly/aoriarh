import { authFetch } from "@/lib/api";

const GENERIC_LINKEDIN_ERROR =
  "La génération du post a échoué. Veuillez réessayer.";

export class LinkedinGenerationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LinkedinGenerationError";
  }
}

export function getLinkedinErrorMessage(error: unknown): string {
  return error instanceof LinkedinGenerationError
    ? error.message
    : GENERIC_LINKEDIN_ERROR;
}

export interface LinkedinSource {
  document_id: string;
  document_name: string;
  source_type_label: string;
  excerpt: string;
  article_nums?: string[] | null;
  numero_pourvoi?: string | null;
}

export interface LinkedinResult {
  post: string;
  character_count: number;
  sources: LinkedinSource[];
  cost_usd: number;
  duration_ms: number;
}

interface LinkedinStreamCallbacks {
  onStart: (sources: LinkedinSource[]) => void;
  onDelta: (content: string) => void;
  onDone: (result: LinkedinResult) => void;
  onError: (message: string) => void;
}

export async function streamLinkedinPost(
  topic: string,
  token: string,
  callbacks: LinkedinStreamCallbacks
): Promise<void> {
  let response: Response;
  try {
    response = await authFetch("/admin/linkedin/generate", {
      method: "POST",
      token,
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ topic }),
    });
  } catch {
    throw new LinkedinGenerationError(
      "Connexion impossible. Vérifiez votre réseau et réessayez."
    );
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const canExposeDetail = [401, 403, 422, 429, 503, 504].includes(
      response.status
    );
    throw new LinkedinGenerationError(
      canExposeDetail && typeof payload?.detail === "string"
        ? payload.detail
        : GENERIC_LINKEDIN_ERROR
    );
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError("Streaming non supporté par le navigateur.");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let eventType = "";
  let dataStr = "";
  let terminalEventReceived = false;

  const processLine = (rawLine: string) => {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
      return;
    }
    if (line.startsWith("data: ")) {
      dataStr = line.slice(6);
      return;
    }
    if (line !== "" || !eventType || !dataStr) return;

    try {
      const parsed = JSON.parse(dataStr);
      switch (eventType) {
        case "linkedin_start":
          callbacks.onStart(parsed.sources);
          break;
        case "linkedin_delta":
          callbacks.onDelta(parsed.content);
          break;
        case "linkedin_done":
          terminalEventReceived = true;
          callbacks.onDone(parsed);
          break;
        case "linkedin_error":
          terminalEventReceived = true;
          callbacks.onError(parsed.message);
          break;
      }
    } catch {
      // Un événement mal formé est ignoré sans toucher au texte déjà affiché.
    }
    eventType = "";
    dataStr = "";
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(processLine);
    }

    buffer += decoder.decode();
    if (buffer) {
      buffer.split("\n").forEach(processLine);
    }
    if (eventType && dataStr) processLine("");

    if (!terminalEventReceived) {
      callbacks.onError(
        "Le flux s'est interrompu. Le texte déjà reçu reste visible."
      );
    }
  } catch {
    callbacks.onError(
      "La connexion au serveur a été interrompue. Le texte déjà reçu reste visible."
    );
  } finally {
    reader.releaseLock();
  }
}
