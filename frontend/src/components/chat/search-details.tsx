import type { SearchDetails } from "@/types/api";

export function SearchDetailsPanel({ details }: { details?: SearchDetails | null }) {
  if (!details || (!details.raw_response && !details.router_raw_response && !details.warnings.length)) return null;
  return (
    <details open className="my-3 rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer">Préparation de la recherche</summary>
      {details.router_raw_response && (
        <pre className="mt-2 whitespace-pre-wrap break-words text-xs">{details.router_raw_response}</pre>
      )}
      {details.warnings.map((warning, index) => <p role="status" key={index}>{warning}</p>)}
      {details.raw_response && (
        <pre className="mt-2 whitespace-pre-wrap break-words text-xs">{details.raw_response}</pre>
      )}
    </details>
  );
}
