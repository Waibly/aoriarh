import { apiFetch } from "@/lib/api";
import type { ChatDocumentReference } from "@/lib/chat-api";

export interface LibraryDocument {
  document_id: string;
  name: string;
  source_type: string;
  uploaded_at: string;
  updated_at: string;
  file_format: string | null;
  file_size: number | null;
  source_sha256: string | null;
}

export interface LibrarySearch {
  name: string;
  uploaded_from: string;
  uploaded_to: string;
}

export function searchChatLibrary(conversationId: string, token: string, search: LibrarySearch, offset = 0) {
  const params = new URLSearchParams({ offset: String(offset), limit: "20" });
  for (const [key, value] of Object.entries(search)) if (value) params.set(key, value);
  return apiFetch<{ items: LibraryDocument[]; has_more: boolean }>(
    `/conversations/${conversationId}/document-library?${params}`, { token },
  );
}

export function prepareLibraryDocument(conversationId: string, token: string, document: LibraryDocument) {
  return apiFetch<ChatDocumentReference>(
    `/conversations/${conversationId}/document-library/${document.document_id}`,
    { token, method: "POST", body: JSON.stringify({ source_sha256: document.source_sha256 }) },
  );
}
