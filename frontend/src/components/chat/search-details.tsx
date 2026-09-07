import type { SearchDetails } from "@/types/api";

export function SearchDetailsPanel(_props: { details?: SearchDetails | null }) {
  // Les détails de recherche sont réservés aux traces/audits protégés et ne
  // sont pas affichés dans les interfaces utilisateur.
  return null;
}
