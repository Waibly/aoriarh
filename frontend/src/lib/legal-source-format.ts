const JORF_SOURCE_TYPES = new Set([
  "loi",
  "ordonnance",
  "decret",
  "arrete",
]);

/**
 * Ajoute uniquement la syntaxe de titre Markdown manquante aux anciens textes
 * JORF. Le contenu juridique et ses retours à la ligne restent inchangés.
 */
export function formatLegalSourceMarkdown(
  text: string,
  sourceType?: string | null
): string {
  if (!JORF_SOURCE_TYPES.has(sourceType ?? "")) return text;

  return text.replace(
    /(^|\n)(Article\s+(?:[\wÀ-ÖØ-öø-ÿ.-]+)(?:\s+\(suite\))?)(?=\s*\n|$)/g,
    "$1### $2"
  );
}
