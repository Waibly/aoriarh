import { resolveSourceReferences } from "@/lib/legal-refs";
import type { MessageSource } from "@/types/api";

export interface SourceEvidence {
  source: MessageSource;
  references: string[];
}

export interface PartitionedSources {
  foundations: SourceEvidence[];
  consulted: MessageSource[];
}

export function partitionSources(
  answer: string,
  sources: MessageSource[]
): PartitionedSources {
  const resolved = resolveSourceReferences(answer, sources);
  const referencesByDocument = new Map(
    resolved.map(({ source, texts }) => [source.document_id, texts])
  );

  return {
    foundations: sources
      .filter((source) => referencesByDocument.has(source.document_id))
      .map((source) => ({
        source,
        references: referencesByDocument.get(source.document_id) ?? [],
      })),
    consulted: sources.filter(
      (source) => !referencesByDocument.has(source.document_id)
    ),
  };
}

export function sourceIdcc(source: MessageSource): string | null {
  if (source.idcc) return source.idcc.padStart(4, "0");
  return (
    source.document_name
      .match(/\bIDCC\s+(\d{1,4})\b/i)?.[1]
      ?.padStart(4, "0") ?? null
  );
}

export function sourceDate(source: MessageSource): string | null {
  const raw = source.date_decision ?? source.content_date;
  if (!raw) return null;
  const parsed = new Date(`${raw.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return raw;
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}
