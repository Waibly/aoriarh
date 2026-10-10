import { reportIncident } from "@/lib/incidents";
import { API_BASE_URL } from "@/lib/api";
import type { MessageSource } from "@/types/api";

/**
 * Client SSE de la démo publique (hero du site → réponse dans l'app).
 *
 * Copie volontaire du parseur de `streamMessage` (chat-api.ts) mais :
 *  - fetch DIRECT, sans token ni logique de refresh (endpoint public) ;
 *  - vise `POST ${API_BASE_URL}/public/ask` ;
 *  - gère l'event `chat_meta` (identifiant de la conversation créée) et l'`upsell`
 *    renvoyé dans `chat_done`.
 */
export interface DemoStreamCallbacks {
  onMeta?: (conversationId: string) => void;
  onStatus?: (step: string) => void;
  onSources: (sources: MessageSource[]) => void;
  onSearchDetails?: (details: import("@/types/api").SearchDetails) => void;
  onDelta: (content: string) => void;
  onDone: (payload: { upsell?: string }) => void;
  onError: (message: string) => void;
}

export interface DemoAskParams {
  message: string;
  turnstileToken?: string | null;
}

export async function streamPublicAsk(
  { message, turnstileToken }: DemoAskParams,
  callbacks: DemoStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/public/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        turnstile_token: turnstileToken ?? null,
      }),
      signal,
    });
  } catch {
    if (signal?.aborted) return;
    callbacks.onError("Connexion impossible. Vérifiez votre réseau et réessayez.");
    return;
  }

  if (!response.ok) {
    // Le backend renvoie un message lisible dans `detail` (plafond, longueur,
    // Turnstile, démo désactivée…). On le remonte tel quel si présent.
    let message = "Une erreur est survenue lors du traitement de votre question.";
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") message = data.detail;
      else if (response.status === 422) message = "La demande n’a pas pu être transmise au service de démonstration (erreur 422).";
    } catch {
      // pas de corps JSON — message générique
    }
    callbacks.onError(message);
    return;
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
  let terminal = false;
  const incidentOptions = { request_id: response.headers?.get("X-Request-ID") };

  function processLine(line: string) {
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataStr = line.slice(6);
    } else if (line === "" && eventType && dataStr) {
      try {
        const parsed = JSON.parse(dataStr);
        switch (eventType) {
          case "chat_meta":
            callbacks.onMeta?.(parsed.conversation_id);
            break;
          case "chat_status":
            callbacks.onStatus?.(parsed.step);
            break;
          case "chat_search_details":
            callbacks.onSearchDetails?.(parsed);
            break;
          case "chat_sources":
            callbacks.onSources(parsed.sources);
            break;
          case "chat_delta":
            callbacks.onDelta(parsed.content);
            break;
          case "chat_done":
            terminal = true;
            callbacks.onDone(parsed);
            break;
          case "chat_error":
            reportIncident("stream_error", incidentOptions);
            terminal = true;
            callbacks.onError(parsed.message);
            break;
        }
      } catch {
        reportIncident("stream_parse_error", incidentOptions);
        throw new Error("Événement SSE illisible");
      }
      eventType = "";
      dataStr = "";
    }
  }

  try {
    while (true) {
      if (signal?.aborted) break;
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        processLine(line);
      }
    }

    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        processLine(line);
      }
      if (eventType && dataStr) {
        processLine("");
      }
    }
    if (!terminal && !signal?.aborted) {
      reportIncident("stream_incomplete", incidentOptions);
      callbacks.onError("La connexion s’est terminée avant la fin de la réponse.");
    }
  } catch {
    if (signal?.aborted) return;
    callbacks.onError(
      "La connexion au serveur a été interrompue. Veuillez réessayer.",
    );
  } finally {
    reader.releaseLock();
  }
}
