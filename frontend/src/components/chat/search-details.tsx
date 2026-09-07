import type { SearchDetails } from "@/types/api";

export function SearchDetailsPanel({ details }: { details?: SearchDetails | null }) {
  // Les réponses brutes du routeur et du planner sont des données
  // d'observabilité destinées aux traces/audits protégés. Elles ne doivent
  // jamais être rendues dans les écrans utilisateurs.
  if (!details || !details.warnings.length) return null;
  return (
    <details open className="my-3 rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer">Préparation de la recherche</summary>
      {details.warnings.map((warning, index) => <p role="status" key={index}>{warning}</p>)}
    </details>
  );
}
