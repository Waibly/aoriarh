import type { Element, Text } from "hast";

import { getSourceGroup } from "@/lib/source-groups";
import type { MessageSource } from "@/types/api";

/**
 * Détection des références juridiques dans le texte d'une réponse et
 * résolution vers la source récupérée correspondante, pour rendre la
 * référence cliquable (ouvre la fiche source).
 *
 * Principe de sûreté : on ne crée JAMAIS de lien si la référence n'existe pas
 * dans les sources du message. Une regex permissive est volontairement
 * compensée par un lookup strict — un lien faux est pire que pas de lien.
 */

export interface RefIndex {
  byArticle: Map<string, MessageSource>;
  byPourvoi: Map<string, MessageSource>;
}

/** Clé canonique d'un article : "R. 4463-3" / "art. R.4463-3" → "R4463-3". */
function normalizeArticleKey(raw: string): string {
  return raw
    .toUpperCase()
    .replace(/[–—]/g, "-") // tirets longs → trait d'union
    .replace(/[.\s  ]/g, ""); // points, espaces (y compris insécables)
}

/** Clé canonique d'un pourvoi : "25-10.127" → "2510127". */
function normalizePourvoi(raw: string): string {
  return raw.replace(/\D/g, "");
}

/**
 * Construit l'index de référencement à partir des sources d'un message.
 * - Pourvois : toute source jurisprudentielle portant un numéro de pourvoi.
 * - Articles L/R/D : uniquement les sources du groupe "legal" (textes légaux et
 *   réglementaires), pour qu'un « art. L… » ne pointe jamais vers une
 *   jurisprudence qui ne fait que le citer.
 * Premier arrivé gagne (les sources sont déjà ordonnées par pertinence).
 */
export function buildRefIndex(sources: MessageSource[]): RefIndex {
  const byArticle = new Map<string, MessageSource>();
  const byPourvoi = new Map<string, MessageSource>();

  for (const source of sources) {
    if (source.numero_pourvoi) {
      const key = normalizePourvoi(source.numero_pourvoi);
      if (key && !byPourvoi.has(key)) byPourvoi.set(key, source);
    }
    if (getSourceGroup(source.source_type) === "legal" && source.article_nums) {
      for (const art of source.article_nums) {
        const key = normalizeArticleKey(art);
        if (key && !byArticle.has(key)) byArticle.set(key, source);
      }
    }
  }

  return { byArticle, byPourvoi };
}

// Référence d'article : "art. R.4463-3", "article L1234-1", "R. 4624-31"…
// Le préfixe "art."/"article" est optionnel et inclus dans le lien quand présent.
// Lettre en MAJUSCULE uniquement (pas de flag `i`) pour éviter de matcher des
// lettres au fil du texte ("or 5", "down 3"…) ; le préfixe accepte les 2 casses.
const ARTICLE_RE = /(?:[Aa]rt(?:icle)?s?\.?\s*)?([LRD])\.?\s?(\d+(?:[-–]\d+)*)/g;
// Numéro de pourvoi / RG : "n° 25-10.127" (cassation) ou "n° 23/03765" (appel).
const POURVOI_RE = /n[°ºo]\s?(\d[\d./-]{4,})/gi;

interface Hit {
  start: number;
  end: number;
  text: string;
  source: MessageSource;
}

function collectHits(value: string, index: RefIndex): Hit[] {
  const hits: Hit[] = [];

  for (const m of value.matchAll(ARTICLE_RE)) {
    const source = index.byArticle.get(normalizeArticleKey(m[1] + m[2]));
    if (source && m.index !== undefined) {
      hits.push({ start: m.index, end: m.index + m[0].length, text: m[0], source });
    }
  }
  for (const m of value.matchAll(POURVOI_RE)) {
    const source = index.byPourvoi.get(normalizePourvoi(m[1]));
    if (source && m.index !== undefined) {
      hits.push({ start: m.index, end: m.index + m[0].length, text: m[0], source });
    }
  }

  // Ordonner et écarter les chevauchements (le premier l'emporte).
  hits.sort((a, b) => a.start - b.start);
  const kept: Hit[] = [];
  let cursor = -1;
  for (const hit of hits) {
    if (hit.start >= cursor) {
      kept.push(hit);
      cursor = hit.end;
    }
  }
  return kept;
}

function refLink(text: string, source: MessageSource): Element {
  return {
    type: "element",
    tagName: "a",
    properties: { href: `#src-${source.document_id}`, className: ["legal-ref"] },
    children: [{ type: "text", value: text }],
  };
}

/**
 * Découpe un nœud texte en segments texte + liens pour chaque référence
 * résolue. Renvoie null si aucune référence résolue (le nœud reste intact).
 */
export function buildReplacements(
  value: string,
  index: RefIndex,
): (Text | Element)[] | null {
  const hits = collectHits(value, index);
  if (hits.length === 0) return null;

  const out: (Text | Element)[] = [];
  let pos = 0;
  for (const hit of hits) {
    if (hit.start > pos) {
      out.push({ type: "text", value: value.slice(pos, hit.start) });
    }
    out.push(refLink(hit.text, hit.source));
    pos = hit.end;
  }
  if (pos < value.length) {
    out.push({ type: "text", value: value.slice(pos) });
  }
  return out;
}
