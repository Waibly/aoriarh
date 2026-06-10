"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Search, ArrowUp, FileText, Sparkles, Loader2 } from "lucide-react";
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
  // On garde à partir du PREMIER "### Article" (le début réel de l'article), pas
  // du dernier (qui serait le marqueur "(suite)" = la fin de l'article).
  const first = t.indexOf("### Article");
  if (first !== -1) t = t.slice(first);
  // Retire tous les marqueurs de titre/jointure de chunks ("### Article Lxxx",
  // "### Article Lxxx (suite)") pour recoller l'article en continu.
  t = t.replace(
    /###\s*Article\s+[LRD]\.?\s*[\w.\-]*\s*(?:\(suite\))?/gi,
    " ",
  );
  t = t
    .replace(/[#>]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  // Retire un éventuel "Article Lxxx (suite)" résiduel en tête.
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

function RelevanceDots({ score }: { score: number }) {
  const level = relevanceLevel(score);
  return (
    <span className="inline-flex items-center gap-0.5" title={`Pertinence ${level}/5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            i <= level ? "bg-primary" : "bg-muted-foreground/25",
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

  const isAdmin = session?.user?.role === "admin";

  const runSearch = useCallback(async () => {
    const token = session?.access_token;
    if (!token || !currentOrg || !query.trim()) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await searchDocuments(currentOrg.id, query.trim(), token);
      setData(res);
    } catch {
      setError("La recherche a échoué. Réessayez dans un instant.");
    } finally {
      setLoading(false);
    }
  }, [session, currentOrg, query]);

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

  return (
    <div className="mx-auto w-full max-w-4xl">
      <div className="rounded-2xl border bg-card p-5 shadow-sm sm:p-6">
        {/* En-tête */}
        <div className="mb-4">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Search className="h-5 w-5 text-primary" />
            Recherche documentaire
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Posez votre question : Aoriarh remonte les textes pertinents, sans
            réponse rédigée.
          </p>
        </div>

        {/* Champ de recherche */}
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
            onClick={runSearch}
            disabled={loading || !query.trim() || !currentOrg}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowUp className="h-4 w-4" />
            )}
          </Button>
        </div>

        {/* Résultats */}
        <div className="mt-6 space-y-4">
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

              <div className="divide-y divide-border">
                {groups.map((g, gi) => (
                  <section
                    key={`${g.head.document_id}-${gi}`}
                    className="py-4 first:pt-0"
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
                      <RelevanceDots score={g.best} />
                    </div>

                    <div className="space-y-3">
                      {g.items.map((c, ci) => (
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
                          <p className="text-sm leading-relaxed text-foreground/90">
                            <Highlighted
                              text={cleanExcerpt(c.excerpt)}
                              terms={terms}
                            />
                          </p>
                        </div>
                      ))}
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
            {!docLoading && docContent && (
              <div className="whitespace-pre-wrap break-words text-sm leading-7 text-foreground/90">
                {cleanFullText(docContent.content)}
              </div>
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
