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
  byDocNumber: Map<string, MessageSource>;
  // Textes cités par DATE (arrêtés surtout, mais aussi décrets/lois/ordonnances
  // quand aucun n° n'est donné). Clé : "<type>:<AAAA-MM-JJ>", ex. "arrete:2026-05-22".
  byTypeDate: Map<string, MessageSource>;
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

/** Clé canonique d'un numéro de texte : "2025-887" → "2025887". */
function normalizeDocNumber(raw: string): string {
  return raw.replace(/\D/g, "");
}

/** Retire les accents (é→e, û→u…) pour comparer mois et types sans casse d'accent. */
function stripAccents(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

const MONTHS_FR: Record<string, string> = {
  janvier: "01", fevrier: "02", mars: "03", avril: "04", mai: "05", juin: "06",
  juillet: "07", aout: "08", septembre: "09", octobre: "10", novembre: "11",
  decembre: "12",
};

/** Types de textes cités par date (le n° existe rarement pour les arrêtés). */
const DATE_SOURCE_TYPES = new Set(["arrete", "decret", "loi", "ordonnance"]);

/**
 * Extrait une date canonique "AAAA-MM-JJ" depuis un texte français
 * ("22 mai 2026", "1er janvier 2026") ou numérique ("22/05/2026"). null sinon.
 */
function extractCanonicalDate(raw: string): string | null {
  const fr = raw.match(/(\d{1,2})(?:er)?\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})/);
  if (fr) {
    const mm = MONTHS_FR[stripAccents(fr[2]).toLowerCase()];
    if (mm) return `${fr[3]}-${mm}-${fr[1].padStart(2, "0")}`;
  }
  const num = raw.match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  if (num) return `${num[3]}-${num[2].padStart(2, "0")}-${num[1].padStart(2, "0")}`;
  return null;
}

/** "Arrêtés" / "décret" → token canonique "arrete" / "decret". */
function normalizeTypeWord(w: string): string {
  return stripAccents(w).toLowerCase().replace(/s$/, "");
}

/** Numéro d'un décret/loi/ordonnance dans le nom d'un document source. */
const DOC_NAME_NUMBER_RE = /n[°ºo]\s?(\d{4}-\d+)/i;

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
  const byDocNumber = new Map<string, MessageSource>();
  const byTypeDate = new Map<string, MessageSource>();

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
    // Numéro de décret/loi/ordonnance extrait du nom du document (ex.
    // « Décret n° 2025-887 du… » → 2025-887), pour rendre la mention du texte
    // cliquable vers son document.
    if (getSourceGroup(source.source_type) === "legal") {
      const num = source.document_name?.match(DOC_NAME_NUMBER_RE);
      if (num) {
        const key = normalizeDocNumber(num[1]);
        if (key && !byDocNumber.has(key)) byDocNumber.set(key, source);
      }
    }
    // Texte cité par DATE (arrêté surtout) : clé "<type>:<AAAA-MM-JJ>" depuis le
    // nom du document (ex. « Arrêté du 22 mai 2026… » → "arrete:2026-05-22").
    if (source.source_type && DATE_SOURCE_TYPES.has(source.source_type)) {
      const date = extractCanonicalDate(source.document_name || "");
      if (date) {
        const key = `${source.source_type}:${date}`;
        if (!byTypeDate.has(key)) byTypeDate.set(key, source);
      }
    }
  }

  return { byArticle, byPourvoi, byDocNumber, byTypeDate };
}

// Référence d'article : "art. R.4463-3", "article L1234-1", "R. 4624-31"…
// Le préfixe "art."/"article" est optionnel et inclus dans le lien quand présent.
// Lettre en MAJUSCULE uniquement (pas de flag `i`) pour éviter de matcher des
// lettres au fil du texte ("or 5", "down 3"…) ; le préfixe accepte les 2 casses.
const ARTICLE_RE = /(?:[Aa]rt(?:icle)?s?\.?\s*)?([LRD])\.?\s?(\d+(?:[-–]\d+)*)/g;
// Numéro de pourvoi / RG : "n° 25-10.127" (cassation) ou "n° 23/03765" (appel).
const POURVOI_RE = /n[°ºo]\s?(\d[\d./-]{4,})/gi;
// Numéro de texte réglementaire : "décret n° 2025-887", "loi n° 2025-1403".
// Le mot (décret/loi/…) précède, ce qui le distingue d'un pourvoi et lui donne
// la priorité (le hit démarre plus tôt et absorbe le "n° …" à l'intérieur).
const DOC_NUMBER_RE = /(décrets?|lois?|ordonnances?|arrêtés?)\s+n[°ºo]\s?(\d{4}-\d+)/gi;
// Texte cité par DATE, sans numéro : "Arrêté du 22/05/2026", "Arrêté du 22 mai
// 2026", "Décret du 17 décembre 2025". Le mot du type précède directement "du".
const DATE_REF_RE =
  /(arrêtés?|décrets?|lois?|ordonnances?)\s+du\s+(\d{1,2}(?:er)?\s+[A-Za-zÀ-ÿ]+\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{4})/gi;

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
  for (const m of value.matchAll(DOC_NUMBER_RE)) {
    const source = index.byDocNumber.get(normalizeDocNumber(m[2]));
    if (source && m.index !== undefined) {
      hits.push({ start: m.index, end: m.index + m[0].length, text: m[0], source });
    }
  }
  for (const m of value.matchAll(DATE_REF_RE)) {
    const date = extractCanonicalDate(m[2]);
    if (!date) continue;
    const source = index.byTypeDate.get(`${normalizeTypeWord(m[1])}:${date}`);
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
