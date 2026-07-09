import { API_BASE_URL } from "@/lib/api";
import type { MessageSource } from "@/types/api";

/**
 * Client SSE de la démo publique (hero du site → réponse dans l'app).
 *
 * Copie volontaire du parseur de `streamMessage` (chat-api.ts) mais :
 *  - fetch DIRECT, sans token ni logique de refresh (endpoint public) ;
 *  - vise `POST ${API_BASE_URL}/public/ask` ;
 *  - gère l'event `chat_meta` (conversation_id, pour les relances) et l'`upsell`
 *    renvoyé dans `chat_done`.
 */
export interface DemoStreamCallbacks {
  onMeta?: (conversationId: string) => void;
  onStatus?: (step: string) => void;
  onSources: (sources: MessageSource[]) => void;
  onDelta: (content: string) => void;
  onDone: (payload: { upsell?: string }) => void;
  onError: (message: string) => void;
}

export interface DemoAskParams {
  message: string;
  turnstileToken?: string | null;
  conversationId?: string | null;
}

export async function streamPublicAsk(
  { message, turnstileToken, conversationId }: DemoAskParams,
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
        conversation_id: conversationId ?? null,
      }),
    });
  } catch {
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
          case "chat_sources":
            callbacks.onSources(parsed.sources);
            break;
          case "chat_delta":
            callbacks.onDelta(parsed.content);
            break;
          case "chat_done":
            callbacks.onDone(parsed);
            break;
          case "chat_error":
            callbacks.onError(parsed.message);
            break;
        }
      } catch {
        // JSON malformé — on ignore
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
  } catch {
    if (signal?.aborted) return;
    callbacks.onError(
      "La connexion au serveur a été interrompue. Veuillez réessayer.",
    );
  } finally {
    reader.releaseLock();
  }
}
