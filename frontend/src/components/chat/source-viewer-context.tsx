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
    throw new Error("useSourceViewer must be used within a SourceViewerProvider");
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
    null,
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
    [openSource, sourcesById],
  );

  const displayedText =
    fullContent ?? selectedSource?.full_text ?? selectedSource?.excerpt ?? "";
  const isTruncated =
    fullContent === null &&
    typeof selectedSource?.full_text === "string" &&
    selectedSource.full_text.trimEnd().endsWith("[…]");

  const handleLoadFullContent = async () => {
    if (!selectedSource || !token) return;
    setFullContentLoading(true);
    setFullContentError(null);
    try {
      const data = await getSourceFullContent(selectedSource.document_id, token);
      setFullContent(data.content);
    } catch (err) {
      setFullContentError(
        err instanceof Error
          ? err.message
          : "Impossible de charger le document complet.",
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
        <DialogContent className="flex max-h-[85vh] sm:max-w-5xl flex-col overflow-hidden">
          <DialogHeader className="shrink-0 border-b border-border pb-4">
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
                    className="rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0] hover:bg-[#652bb0]/10 dark:bg-[#652bb0]/20 dark:text-[#652bb0] dark:hover:bg-[#652bb0]/20 text-xs"
                  >
                    {selectedSource?.source_type_label}
                  </Badge>
                  <span className="text-muted-foreground text-xs">
                    Niveau {selectedSource?.norme_niveau}
                  </span>
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
            <div className="prose prose-sm dark:prose-invert max-w-none pr-4 text-[0.9375rem] leading-7 text-foreground [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_p]:my-3 [&_p]:leading-7 [&_ul]:my-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_li]:leading-7 [&_li::marker]:text-foreground/70 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_table]:my-3 [&_table]:border-collapse [&_table]:text-xs [&_table]:w-full [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_td]:align-top">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
              >
                {displayedText}
              </ReactMarkdown>
            </div>
            {(isTruncated || fullContentError) && (
              <div className="mt-3 flex items-center justify-center gap-3 border-t border-border pt-3">
                {fullContentError ? (
                  <span className="text-xs text-destructive">
                    {fullContentError}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">
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
                  {fullContentLoading ? "Chargement…" : "Voir le document complet"}
                </Button>
              </div>
            )}
            {fullContent !== null && (
              <div className="mt-3 border-t border-border pt-3 text-center">
                <span className="text-xs text-muted-foreground">
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
  props: ComponentProps<"a"> & { node?: unknown },
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
