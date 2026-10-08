import { apiFetch, authFetch } from "@/lib/api";
import type { Conversation, ConversationCaseFile } from "@/types/api";

export interface Dossier {
  id: string;
  organisation_id: string;
  name: string;
  description: string;
  instructions: string;
  pinned: boolean;
  archived_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  conversation_count: number;
  document_count: number;
}
export interface DossierDocument {
  id: string;
  document_id: string | null;
  extraction_id: string | null;
  name: string;
  description: string;
  scope: "dossier" | "entreprise";
  status: "ready" | "preparing" | "error" | "unavailable";
  file_format: string | null;
  created_at: string;
}
export interface DossierDetail extends Dossier {
  case_file: ConversationCaseFile;
  conversations: Conversation[];
  documents: DossierDocument[];
  has_more: boolean;
}
export function dossierChanged() {
  window.dispatchEvent(new Event("dossiers-updated"));
  window.dispatchEvent(new Event("conversation-updated"));
}
export const getDossier = (id: string, token: string, offset = 0, q = "") =>
  apiFetch<DossierDetail>(
    `/dossiers/${id}?offset=${offset}&q=${encodeURIComponent(q)}`,
    { token }
  );
export const listDossiers = (
  org: string,
  token: string,
  archived = false,
  q = "",
  offset = 0
) =>
  apiFetch<{ items: Dossier[]; has_more: boolean }>(
    `/dossiers/?organisation_id=${org}${archived ? "&archived=true" : ""}&q=${encodeURIComponent(q)}&offset=${offset}`,
    { token }
  );
export const listRecentDossiers = (org: string, token: string) =>
  apiFetch<{ items: Dossier[]; has_more: boolean }>(
    `/dossiers/?organisation_id=${org}&order=recent&limit=4`, { token }
  );
export async function dossierOperation(
  id: string,
  token: string,
  suffix: string,
  body: object,
  method = "POST"
) {
  const result = await apiFetch<DossierDetail>(`/dossiers/${id}${suffix}`, {
    token,
    method,
    body: JSON.stringify(body),
  });
  dossierChanged();
  return result;
}
export async function uploadDossierDocument(
  id: string,
  token: string,
  file: File,
  replaceDocumentId?: string,
  expectedCaseVersion?: number
) {
  const body = new FormData();
  body.append("file", file);
  const response = await authFetch(
    `/dossiers/${id}/documents${replaceDocumentId ? `?replace_document_id=${replaceDocumentId}&expected_case_version=${expectedCaseVersion}` : ""}`,
    {
      method: "POST",
      body,
      token,
    }
  );
  if (!response.ok) {
    dossierChanged();
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : "Import impossible. Vérifiez le fichier puis réessayez."
    );
  }
  dossierChanged();
  return response.json() as Promise<DossierDetail>;
}
export async function downloadDossierDocument(
  id: string,
  token: string,
  document: DossierDocument
) {
  if (!document.document_id) throw new Error("Ce document n’est plus disponible.");
  const response = await authFetch(
    `/dossiers/${id}/documents/${document.document_id}/download`,
    { token }
  );
  if (!response.ok) throw new Error("Document non accessible");
  const url = URL.createObjectURL(await response.blob());
  const a = window.document.createElement("a");
  a.href = url;
  a.download = document.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
