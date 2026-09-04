"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { useSession } from "next-auth/react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { BookOpen, FileText, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSourceFullContent } from "@/lib/chat-api";
import { formatLegalSourceMarkdown } from "@/lib/legal-source-format";
import { sourceDate, sourceIdcc } from "@/lib/source-evidence";
import type { MessageSource } from "@/types/api";

export function formatJurisprudenceRef(source: MessageSource): string | null {
  if (!source.numero_pourvoi && !source.date_decision) return null;
  const parts: string[] = [];
  if (source.juridiction) {
    let j = source.juridiction;
    if (source.chambre) j = `${j} ${source.chambre}`;
    parts.push(j);
  }
  if (source.date_decision) parts.push(source.date_decision);
  if (source.numero_pourvoi) parts.push(`n° ${source.numero_pourvoi}`);
  return parts.join(", ");
}

interface SourceViewerValue {
  openSource: (source: MessageSource) => void;
  sourcesById: Map<string, MessageSource>;
}

const SourceViewerContext = createContext<SourceViewerValue | null>(null);

export function useSourceViewer(): SourceViewerValue {
  const ctx = useContext(SourceViewerContext);
  if (!ctx) {
    throw new Error(
      "useSourceViewer must be used within a SourceViewerProvider"
    );
  }
  return ctx;
}

/**
 * Fournit l'ouverture de la fiche source (modal) à toute une bulle de message :
 * les cartes sources ET les références cliquables dans le markdown appellent le
 * même `openSource`. Le Dialog est rendu une seule fois ici.
 */
export function SourceViewerProvider({
  sources,
  children,
}: {
  sources: MessageSource[];
  children: ReactNode;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [selectedSource, setSelectedSource] = useState<MessageSource | null>(
    null
  );
  // When the user clicks "Voir le document complet", we replace the
  // retrieval excerpt with the full text fetched from the storage.
  const [fullContent, setFullContent] = useState<string | null>(null);
  const [fullContentLoading, setFullContentLoading] = useState(false);
  const [fullContentError, setFullContentError] = useState<string | null>(null);

  // Reset the expanded full-content view each time we open a new source.
  useEffect(() => {
    setFullContent(null);
    setFullContentLoading(false);
    setFullContentError(null);
  }, [selectedSource]);

  const openSource = useCallback((source: MessageSource) => {
    setSelectedSource(source);
  }, []);

  const sourcesById = useMemo(() => {
    const map = new Map<string, MessageSource>();
    for (const source of sources) {
      if (!map.has(source.document_id)) map.set(source.document_id, source);
    }
    return map;
  }, [sources]);

  const value = useMemo<SourceViewerValue>(
    () => ({ openSource, sourcesById }),
    [openSource, sourcesById]
  );

  const rawDisplayedText =
    fullContent ?? selectedSource?.full_text ?? selectedSource?.excerpt ?? "";
  const displayedText = formatLegalSourceMarkdown(
    rawDisplayedText,
    selectedSource?.source_type
  );
  const displayedExcerpt = formatLegalSourceMarkdown(
    selectedSource?.excerpt ?? "",
    selectedSource?.source_type
  );
  const selectedIdcc = selectedSource ? sourceIdcc(selectedSource) : null;
  const selectedDate = selectedSource ? sourceDate(selectedSource) : null;
  const isTruncated =
    fullContent === null &&
    typeof selectedSource?.full_text === "string" &&
    selectedSource.full_text.trimEnd().endsWith("[…]");

  const handleLoadFullContent = async () => {
    if (!selectedSource || !token) return;
    setFullContentLoading(true);
    setFullContentError(null);
    try {
      const data = await getSourceFullContent(
        selectedSource.document_id,
        token
      );
      setFullContent(data.content);
    } catch (err) {
      setFullContentError(
        err instanceof Error
          ? err.message
          : "Impossible de charger le document complet."
      );
    } finally {
      setFullContentLoading(false);
    }
  };

  return (
    <SourceViewerContext.Provider value={value}>
      {children}

      <Dialog
        open={selectedSource !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedSource(null);
        }}
      >
        <DialogContent className="flex max-h-[85vh] flex-col overflow-hidden sm:max-w-5xl">
          <DialogHeader className="border-border shrink-0 border-b pb-4">
            <div className="flex items-center gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#652bb0]/10 dark:bg-[#652bb0]/20">
                <FileText className="size-5 text-[#652bb0] dark:text-[#652bb0]" />
              </div>
              <div className="min-w-0">
                <DialogTitle className="truncate text-base">
                  {selectedSource &&
                    (formatJurisprudenceRef(selectedSource) ||
                      selectedSource.document_name)}
                </DialogTitle>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    className="rounded-full border-[#652bb0] bg-[#652bb0]/10 text-xs text-[#652bb0] hover:bg-[#652bb0]/10 dark:bg-[#652bb0]/20 dark:text-[#652bb0] dark:hover:bg-[#652bb0]/20"
                  >
                    {selectedSource?.source_type_label}
                  </Badge>
                  <span className="text-muted-foreground text-xs">
                    Niveau {selectedSource?.norme_niveau}
                  </span>
                  {selectedIdcc && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      IDCC {selectedIdcc}
                    </Badge>
                  )}
                  {selectedDate && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      {selectedDate}
                    </Badge>
                  )}
                  {selectedSource?.corpus_status ===
                    "available_at_answer_time" && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      Disponible lors de la réponse
                    </Badge>
                  )}
                  {selectedSource?.legal_status && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      {selectedSource.legal_status}
                    </Badge>
                  )}
                  {selectedSource?.solution && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      {selectedSource.solution}
                    </Badge>
                  )}
                  {selectedSource?.publication && (
                    <Badge variant="outline" className="rounded-full text-xs">
                      {selectedSource.publication}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
          </DialogHeader>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {selectedSource?.excerpt && (
              <div className="mb-4 rounded-lg border border-[#652bb0]/20 bg-white px-4 py-3">
                <p className="mb-1 text-xs font-semibold tracking-wide text-[#652bb0] uppercase">
                  Passage sélectionné par la recherche
                </p>
                <div className="prose prose-sm max-w-none text-sm leading-6 text-slate-700 [&_h1]:my-1 [&_h1]:text-sm [&_h1]:leading-6 [&_h1]:font-semibold [&_h2]:my-1 [&_h2]:text-sm [&_h2]:leading-6 [&_h2]:font-semibold [&_h3]:my-1 [&_h3]:text-sm [&_h3]:leading-6 [&_h3]:font-semibold [&_li]:my-0 [&_li]:leading-6 [&_li]:whitespace-pre-line [&_ol]:my-1 [&_ol]:pl-5 [&_p]:my-1 [&_p]:leading-6 [&_p]:whitespace-pre-line [&_strong]:font-semibold [&_ul]:my-1 [&_ul]:pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeSanitize]}
                    skipHtml
                    components={{
                      a: ({ children }) => <span>{children}</span>,
                    }}
                  >
                    {displayedExcerpt}
                  </ReactMarkdown>
                </div>
              </div>
            )}
            <p className="text-muted-foreground mb-2 text-xs font-semibold tracking-wide uppercase">
              Contexte documentaire
            </p>
            <div className="prose prose-sm dark:prose-invert text-foreground [&_li::marker]:text-foreground/70 [&_th]:border-border [&_th]:bg-muted [&_td]:border-border max-w-none pr-4 text-[0.9375rem] leading-7 [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_li]:my-0.5 [&_li]:leading-7 [&_li]:whitespace-pre-line [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-3 [&_p]:leading-7 [&_p]:whitespace-pre-line [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-xs [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_td]:align-top [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
              >
                {displayedText}
              </ReactMarkdown>
            </div>
            {(isTruncated || fullContentError) && (
              <div className="border-border mt-3 flex items-center justify-center gap-3 border-t pt-3">
                {fullContentError ? (
                  <span className="text-destructive text-xs">
                    {fullContentError}
                  </span>
                ) : (
                  <span className="text-muted-foreground text-xs">
                    Cet extrait a été tronqué pour la lisibilité.
                  </span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleLoadFullContent}
                  disabled={fullContentLoading}
                >
                  {fullContentLoading ? (
                    <Loader2 className="mr-2 size-4 animate-spin" />
                  ) : (
                    <BookOpen className="mr-2 size-4" />
                  )}
                  {fullContentLoading
                    ? "Chargement…"
                    : "Voir le document complet"}
                </Button>
              </div>
            )}
            {fullContent !== null && (
              <div className="border-border mt-3 border-t pt-3 text-center">
                <span className="text-muted-foreground text-xs">
                  Document complet affiché.
                </span>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </SourceViewerContext.Provider>
  );
}

/**
 * Composant `a` pour react-markdown : intercepte les liens `#src-<document_id>`
 * générés par le plugin rehype-legal-refs et ouvre la fiche source au clic.
 * Les liens normaux restent inchangés.
 */
export function LegalRefAnchor(
  props: ComponentProps<"a"> & { node?: unknown }
) {
  const ctx = useContext(SourceViewerContext);
  const { href, children } = props;

  if (href && href.startsWith("#src-") && ctx) {
    const source = ctx.sourcesById.get(href.slice("#src-".length));
    if (source) {
      return (
        <a
          href={href}
          className="cursor-pointer"
          title="Ouvrir le passage source"
          onClick={(e) => {
            e.preventDefault();
            ctx.openSource(source);
          }}
        >
          {children}
        </a>
      );
    }
  }

  // Lien normal — retirer la prop hast `node` avant de la passer au DOM.
  const rest: Record<string, unknown> = { ...props };
  delete rest.node;
  return <a {...(rest as ComponentProps<"a">)} />;
}
