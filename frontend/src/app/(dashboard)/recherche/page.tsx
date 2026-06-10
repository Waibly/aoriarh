"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Search, ArrowUp, FileText, Sparkles, Loader2, Star } from "lucide-react";
import { useOrg } from "@/lib/org-context";
import {
  searchDocuments,
  type DocSearchCard,
  type DocSearchResponse,
} from "@/lib/search-api";
import { getSourceFullContent, type SourceFullContent } from "@/lib/chat-api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";

// --- Surlignage ------------------------------------------------------------
const STOPWORDS = new Set([
  "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "au", "aux",
  "en", "dans", "par", "pour", "sur", "que", "qui", "quoi", "est", "ce", "cet",
  "cette", "ces", "il", "elle", "on", "ne", "pas", "plus", "avec", "sans", "se",
  "si", "quel", "quelle", "quels", "quelles", "comment", "quand", "son", "sa",
  "ses", "leur", "leurs", "mon", "ma", "mes", "the", "estce",
  "sont", "ete", "etre", "fait", "font", "par", "ont", "ainsi", "dont", "lors",
  "selon", "tout", "tous", "toute", "toutes", "leur", "cas",
]);

function norm(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]/g, "");
}

function buildTerms(query: string): Set<string> {
  // Surligner uniquement les mots de la question de l'utilisateur, pas les
  // variantes de recherche (qui contiennent tout le vocabulaire juridique et
  // feraient tout s'allumer).
  const terms = new Set<string>();
  for (const w of query.split(/\s+/)) {
    const n = norm(w);
    if (n.length >= 4 && !STOPWORDS.has(n)) terms.add(n);
  }
  return terms;
}

/**
 * Nettoie l'extrait : retire le fil d'Ariane markdown (## … > … ### Article X)
 * et tronque pour garder des cartes compactes. Le document complet reste à un
 * clic.
 */
function cleanExcerpt(text: string, max = 480): string {
  let t = text;
  // L'article fusionné commence par un fil d'Ariane ("## Partie … ### Article X").
  // On garde à partir du PREMIER "### Article" (le début réel de l'article).
  const first = t.indexOf("### Article");
  if (first !== -1) t = t.slice(first);
  // Recolle les sous-chunks ("### Article Lxxx (suite)") en sauts de ligne.
  t = t.replace(/###\s*Article\s+[LRD]\.?\s*[\w.\-]*\s*(?:\(suite\))?/gi, "\n");
  t = t.replace(/[#>]+/g, " ");
  // Tableaux markdown : retirer les lignes de séparation (| --- | --- |) et
  // transformer les barres restantes en séparateurs lisibles, pas en "|" bruts.
  t = t.replace(/\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?/g, " ");
  t = t.replace(/\s*\|\s*/g, " · ");
  t = t.replace(/(?:\s·)+/g, " ·").replace(/·\s*·/g, "·");
  // Mise en page : un saut de ligne avant chaque énumérateur juridique
  // (1° 2° … et a) b) …) pour casser le pavé.
  t = t.replace(/\s+(\d{1,2}°)/g, "\n$1");
  t = t.replace(/\s+([a-z]\)\s)/g, "\n$1");
  // Nettoyage : collapse espaces, garde et normalise les sauts de ligne.
  t = t
    .replace(/[ \t]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{2,}/g, "\n")
    .trim();
  // Retire un "Article Lxxx (suite)" résiduel en tête.
  t = t.replace(/^Article\s+[LRD]\.?\s*\d[\w.\-]*\s*(?:\(suite\))?\s*/i, "").trim();
  if (t.length > max) {
    t = t.slice(0, max).replace(/\s+\S*$/, "") + " …";
  }
  return t;
}

/** Nettoie le texte intégral pour le volet : retire les lignes vides en excès. */
function cleanFullText(text: string): string {
  return text.replace(/\n{3,}/g, "\n\n").trim();
}

/**
 * Borne le contenu rendu dans le volet. Les codes (Code du travail…) font
 * plusieurs Mo : tout rendre en markdown crée un DOM énorme, lent à monter ET à
 * démonter (fermeture qui rame). On limite à une fenêtre, centrée si possible
 * sur l'article cliqué.
 */
function clampDoc(
  content: string,
  card: DocSearchCard | null,
  max = 40000,
): { text: string; truncated: boolean } {
  const text = cleanFullText(content);
  if (text.length <= max) return { text, truncated: false };
  let start = 0;
  const art = card?.article_nums?.[0];
  if (art) {
    const pat = art
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/^([LRD])/, "$1\\.?\\s?");
    const m = text.match(new RegExp(pat));
    if (m && m.index !== undefined && m.index > max / 2) {
      start = m.index - Math.floor(max / 2);
    }
  }
  let slice = text.slice(start, start + max);
  if (start > 0) slice = "[…]\n\n" + slice;
  if (start + max < text.length) slice = slice + "\n\n[…]";
  return { text: slice, truncated: true };
}

function Highlighted({ text, terms }: { text: string; terms: Set<string> }) {
  if (!terms.size) return <>{text}</>;
  const parts = text.split(/(\s+)/);
  return (
    <>
      {parts.map((part, i) => {
        const n = norm(part);
        const match = n.length >= 3 && terms.has(n);
        return match ? (
          <mark
            key={i}
            className="rounded-[3px] bg-primary/15 px-0.5 font-medium text-foreground"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </>
  );
}

// --- Pertinence ------------------------------------------------------------
function relevanceLevel(score: number): number {
  if (score >= 0.7) return 5;
  if (score >= 0.55) return 4;
  if (score >= 0.4) return 3;
  if (score >= 0.25) return 2;
  return 1;
}

function RelevanceStars({ score }: { score: number }) {
  const level = relevanceLevel(score);
  return (
    <span
      className="inline-flex items-center gap-0.5"
      title={`Pertinence ${level}/5`}
    >
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={cn(
            "h-3.5 w-3.5",
            i <= level
              ? "fill-primary text-primary"
              : "fill-transparent text-muted-foreground/30",
          )}
        />
      ))}
    </span>
  );
}

// --- Référence d'une carte -------------------------------------------------
function cardReference(c: DocSearchCard): string {
  if (c.numero_pourvoi || c.date_decision) {
    const bits = [c.juridiction, c.chambre, c.date_decision]
      .filter(Boolean)
      .join(" ");
    return [bits, c.numero_pourvoi ? `n° ${c.numero_pourvoi}` : ""]
      .filter(Boolean)
      .join(", ");
  }
  if (c.article_nums && c.article_nums.length) {
    return `Art. ${c.article_nums.join(" · ")}`;
  }
  return c.section_path || c.document_name;
}

const SUGGESTIONS = [
  "Salariés protégés",
  "Durée de la période d'essai d'un cadre",
  "Contrepartie obligatoire en repos",
  "Indemnité légale de licenciement",
];

// --- Page ------------------------------------------------------------------
export default function RechercheDocumentairePage() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();

  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DocSearchResponse | null>(null);

  // Drawer document complet
  const [openDoc, setOpenDoc] = useState(false);
  const [docLoading, setDocLoading] = useState(false);
  const [docContent, setDocContent] = useState<SourceFullContent | null>(null);
  const [selectedCard, setSelectedCard] = useState<DocSearchCard | null>(null);
  // Extraits dépliés (passage retrouvé en entier), par clé groupe-item.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpanded = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const terms = useMemo(() => buildTerms(data?.query_used ?? ""), [data]);

  // Regroupement par document : les articles d'un même document sont rassemblés
  // (ex. tous les articles du Code du travail dans un seul bloc). Groupes triés
  // par meilleure pertinence. 100% frontend : ne touche pas le pipeline.
  const groups = useMemo(() => {
    if (!data) return [];
    const map = new Map<
      string,
      { head: DocSearchCard; items: DocSearchCard[]; best: number }
    >();
    for (const c of data.results) {
      const g = map.get(c.document_id);
      if (g) {
        g.items.push(c);
        if (c.score > g.best) g.best = c.score;
      } else {
        map.set(c.document_id, { head: c, items: [c], best: c.score });
      }
    }
    return Array.from(map.values()).sort((a, b) => b.best - a.best);
  }, [data]);

  // Contenu borné pour le volet (perf sur les gros documents type codes).
  const docMarkdown = useMemo(
    () => (docContent ? clampDoc(docContent.content, selectedCard) : null),
    [docContent, selectedCard],
  );

  const isAdmin = session?.user?.role === "admin";

  const runSearch = useCallback(
    async (q?: string) => {
      const text = (q ?? query).trim();
      const token = session?.access_token;
      if (!token || !currentOrg || !text) return;
      setQuery(text);
      setLoading(true);
      setError(null);
      setData(null);
      setExpanded(new Set());
      try {
        const res = await searchDocuments(currentOrg.id, text, token);
        setData(res);
      } catch {
        setError("La recherche a échoué. Réessayez dans un instant.");
      } finally {
        setLoading(false);
      }
    },
    [session, currentOrg, query],
  );

  const openFullDocument = useCallback(
    async (card: DocSearchCard) => {
      const token = session?.access_token;
      if (!token) return;
      setSelectedCard(card);
      setOpenDoc(true);
      setDocLoading(true);
      setDocContent(null);
      try {
        const content = await getSourceFullContent(card.document_id, token);
        setDocContent(content);
      } catch {
        setDocContent(null);
      } finally {
        setDocLoading(false);
      }
    },
    [session],
  );

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16 text-center text-muted-foreground">
        Cette fonctionnalité est réservée aux administrateurs.
      </div>
    );
  }

  const hasResults = data && data.results.length > 0;
  const hasSearched = loading || data !== null;

  const searchField = (
    <div className="flex items-end gap-2 rounded-xl border border-input bg-background px-4 py-3">
      <textarea
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            runSearch();
          }
        }}
        placeholder="Ex : contrepartie obligatoire en repos au-delà du contingent"
        rows={1}
        className="flex-1 resize-none bg-transparent py-0.5 text-base text-foreground outline-none placeholder:text-muted-foreground"
      />
      <Button
        size="icon-sm"
        onClick={() => runSearch()}
        disabled={loading || !query.trim() || !currentOrg}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <ArrowUp className="h-4 w-4" />
        )}
      </Button>
    </div>
  );

  if (!hasSearched) {
    // État à vide — pleine hauteur, disposition du WelcomeScreen du chat.
    return (
      <div className="flex flex-1 flex-col items-center justify-center rounded-xl bg-white px-4 py-8 duration-500 animate-in fade-in dark:bg-card">
        <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
          <Search className="h-8 w-8 text-primary" />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Recherche documentaire
        </h1>
        <p className="mt-1 text-base text-muted-foreground">
          Le moteur de recherche juridique
        </p>
        <p className="mt-4 max-w-md text-center text-sm text-muted-foreground">
          Posez votre question : Aoriarh remonte les textes pertinents (lois,
          jurisprudence, conventions), sans réponse rédigée.
        </p>
        <div className="mt-8 w-full max-w-2xl">{searchField}</div>
        <div className="mt-6 grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => runSearch(s)}
              className="flex items-center gap-2 rounded-xl bg-primary/10 px-4 py-3 text-left text-sm text-foreground transition-colors hover:bg-primary/20"
            >
              <Search className="size-4 shrink-0 text-primary" />
              {s}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4 dark:bg-card">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full min-w-0 max-w-4xl space-y-4 px-2 py-1 sm:px-4">
          <div className="flex items-center gap-2">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <Search className="h-5 w-5 text-primary" />
              Recherche documentaire
            </h1>
          </div>

          {searchField}

          {/* Résultats */}
          <div className="space-y-4">
          {loading && (
            <div className="space-y-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-24 w-full rounded-xl" />
              ))}
            </div>
          )}

          {error && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              {error}
            </p>
          )}

          {data && data.out_of_scope && (
            <p className="rounded-lg border bg-muted px-4 py-3 text-sm text-muted-foreground">
              Cette question ne semble pas relever du droit social. Reformulez
              pour cibler une règle RH précise.
            </p>
          )}

          {data && !data.out_of_scope && !hasResults && (
            <p className="rounded-lg border bg-muted px-4 py-3 text-sm text-muted-foreground">
              Aucune source pertinente trouvée pour cette question. Essayez de la
              reformuler.
            </p>
          )}

          {hasResults && (
            <>
              {/* Encart payant — en tête des résultats */}
              <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
                <p className="flex items-center gap-2 font-medium text-primary">
                  <Sparkles className="h-4 w-4 shrink-0" />
                  Les textes, vous les avez. L&apos;analyse de votre cas,
                  c&apos;est Aoriarh qui la fait.
                </p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Aoriarh lit ces sources et vous donne la marche à suivre,
                  appliquée à votre situation.
                </p>
                <Button className="mt-3" size="sm" asChild>
                  <Link href="/chat">Demander l&apos;analyse à Aoriarh</Link>
                </Button>
              </div>

              <p className="text-xs text-muted-foreground">
                {data.results.length} extrait
                {data.results.length > 1 ? "s" : ""} dans {groups.length} document
                {groups.length > 1 ? "s" : ""} · triés par pertinence
              </p>

              <div className="space-y-6">
                {groups.map((g, gi) => (
                  <section
                    key={`${g.head.document_id}-${gi}`}
                    className="rounded-xl border bg-card p-5 shadow-sm"
                  >
                    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <Badge variant="secondary" className="font-normal">
                          {g.head.source_type_label}
                        </Badge>
                        <span className="text-sm font-semibold">
                          {g.head.document_name}
                        </span>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="text-xs text-muted-foreground">
                          Pertinence
                        </span>
                        <RelevanceStars score={g.best} />
                      </div>
                    </div>

                    <div className="space-y-5">
                      {g.items.map((c, ci) => {
                        const key = `${gi}-${ci}`;
                        const isOpen = expanded.has(key);
                        const full = cleanExcerpt(c.excerpt, 100000);
                        const short = cleanExcerpt(c.excerpt);
                        const canExpand = full.length > short.length;
                        return (
                          <div
                            key={ci}
                            className={cn(
                              g.items.length > 1 &&
                                "border-l-2 border-primary/20 pl-3",
                            )}
                          >
                            {g.items.length > 1 && (
                              <p className="mb-0.5 text-sm font-medium text-primary">
                                {cardReference(c)}
                              </p>
                            )}
                            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                              <Highlighted
                                text={isOpen ? full : short}
                                terms={terms}
                              />
                            </p>
                            {canExpand && (
                              <button
                                onClick={() => toggleExpanded(key)}
                                className="mt-1 text-xs font-medium text-primary hover:underline"
                              >
                                {isOpen ? "Réduire" : "Voir l'extrait complet"}
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    <div className="mt-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-auto px-0 text-primary hover:bg-transparent hover:underline"
                        onClick={() => openFullDocument(g.head)}
                      >
                        <FileText className="mr-1 h-4 w-4" />
                        Voir le document complet
                      </Button>
                    </div>
                  </section>
                ))}
              </div>
            </>
          )}
          </div>
        </div>
      </div>

      {/* Drawer document complet */}
      <Sheet open={openDoc} onOpenChange={setOpenDoc}>
        <SheetContent
          side="right"
          className="flex w-full flex-col gap-0 p-0 sm:max-w-2xl"
        >
          <SheetHeader className="border-b px-6 py-4">
            {selectedCard && (
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="font-normal">
                  {selectedCard.source_type_label}
                </Badge>
                <span className="text-sm font-semibold text-foreground">
                  {cardReference(selectedCard)}
                </span>
              </div>
            )}
            <SheetTitle className="pr-8 text-left text-sm font-normal text-muted-foreground">
              {docContent?.name ?? selectedCard?.document_name ?? "Document"}
            </SheetTitle>
          </SheetHeader>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {docLoading && (
              <div className="space-y-3">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} className="h-4 w-full" />
                ))}
              </div>
            )}
            {!docLoading && docMarkdown && (
              <>
                {docMarkdown.truncated && (
                  <p className="mb-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                    Document volumineux : extrait affiché autour de la source.
                  </p>
                )}
                <div className="prose prose-sm dark:prose-invert max-w-none text-[0.9375rem] leading-7 text-foreground [&_h1]:mb-3 [&_h1]:mt-6 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_li]:my-0.5 [&_li]:leading-7 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-3 [&_p]:leading-7 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&>*:first-child]:mt-0">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeSanitize]}
                  >
                    {docMarkdown.text}
                  </ReactMarkdown>
                </div>
              </>
            )}
            {!docLoading && !docContent && (
              <p className="text-sm text-muted-foreground">
                Impossible de charger le document.
              </p>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
