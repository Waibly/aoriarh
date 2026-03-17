import { apiFetch, authFetch } from "@/lib/api";
import type {
  Conversation,
  ConversationWithMessages,
  ChatApiResponse,
  MessageSource,
} from "@/types/api";

export async function createConversation(
  organisationId: string,
  token: string,
  title?: string,
): Promise<Conversation> {
  return apiFetch<Conversation>("/conversations/", {
    method: "POST",
    body: JSON.stringify({ organisation_id: organisationId, title }),
    token,
  });
}

export async function listConversations(
  organisationId: string,
  token: string,
): Promise<Conversation[]> {
  return apiFetch<Conversation[]>(
    `/conversations/?organisation_id=${organisationId}`,
    { token },
  );
}

export async function getConversation(
  conversationId: string,
  token: string,
): Promise<ConversationWithMessages> {
  return apiFetch<ConversationWithMessages>(
    `/conversations/${conversationId}`,
    { token },
  );
}

export async function deleteConversation(
  conversationId: string,
  token: string,
): Promise<void> {
  return apiFetch<void>(`/conversations/${conversationId}`, {
    method: "DELETE",
    token,
  });
}

export async function sendMessage(
  conversationId: string,
  message: string,
  token: string,
): Promise<ChatApiResponse> {
  return apiFetch<ChatApiResponse>(
    `/conversations/${conversationId}/chat`,
    {
      method: "POST",
      body: JSON.stringify({ message }),
      token,
    },
  );
}

export async function updateMessageFeedback(
  messageId: string,
  feedback: "up" | "down" | null,
  token: string,
  comment?: string | null,
): Promise<void> {
  await apiFetch(`/conversations/messages/${messageId}/feedback`, {
    method: "PATCH",
    body: JSON.stringify({ feedback, comment: comment ?? null }),
    token,
  });
}

export interface StreamCallbacks {
  onStatus?: (step: string) => void;
  onSources: (sources: MessageSource[]) => void;
  onDelta: (content: string) => void;
  onDone: (ids: { message_id: string; answer_id: string }) => void;
  onError: (message: string) => void;
}

export async function streamMessage(
  conversationId: string,
  message: string,
  token: string,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  // Do NOT pass signal to fetch — React Strict Mode aborts it in dev.
  // Instead we check signal.aborted manually in the read loop.
  const response = await authFetch(
    `/conversations/${conversationId}/chat/stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      token,
    },
  );

  if (!response.ok) {
    callbacks.onError(
      "Une erreur est survenue lors du traitement de votre question.",
    );
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError("Streaming non supporté par le navigateur.");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  // Persist across reads so split events are reassembled correctly
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
        // Malformed JSON — skip
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

    // Flush remaining buffer after stream ends
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
