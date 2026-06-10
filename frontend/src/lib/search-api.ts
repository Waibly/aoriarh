import { apiFetch } from "@/lib/api";

export interface DocSearchCard {
  document_id: string;
  document_name: string;
  source_type: string;
  source_type_label: string;
  norme_niveau: number;
  score: number;
  excerpt: string;
  article_nums?: string[] | null;
  section_path?: string | null;
  juridiction?: string | null;
  chambre?: string | null;
  numero_pourvoi?: string | null;
  date_decision?: string | null;
  solution?: string | null;
  publication?: string | null;
}

export interface DocSearchResponse {
  query_used: string;
  variants: string[];
  out_of_scope: boolean;
  results: DocSearchCard[];
}

/**
 * Recherche documentaire (sources seules, sans génération). Admin v1.
 */
export async function searchDocuments(
  organisationId: string,
  query: string,
  token: string,
): Promise<DocSearchResponse> {
  return apiFetch<DocSearchResponse>("/conversations/search", {
    method: "POST",
    body: JSON.stringify({ organisation_id: organisationId, query }),
    token,
  });
}
