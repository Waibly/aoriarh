"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { ChevronRight, FileText, Loader2, BookOpen, HelpCircle } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSourceFullContent } from "@/lib/chat-api";
import { groupSources } from "@/lib/source-groups";
import type { MessageSource } from "@/types/api";

function formatJurisprudenceRef(source: MessageSource): string | null {
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

interface MessageSourcesProps {
  sources: MessageSource[];
}

export function MessageSources({ sources }: MessageSourcesProps) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [isOpen, setIsOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState<MessageSource | null>(
    null,
  );
  const groups = groupSources(sources);
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

  const displayedText = fullContent ?? selectedSource?.full_text ?? selectedSource?.excerpt ?? "";
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
        token,
      );
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
    <>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="mt-4 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-[#652bb0] transition-colors hover:bg-[#652bb0]/5 dark:text-[#652bb0] dark:hover:bg-[#652bb0]/10">
          <ChevronRight
            className={`size-4 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
          />
          <FileText className="size-4" />
          {sources.length} source{sources.length > 1 ? "s" : ""} consultée
          {sources.length > 1 ? "s" : ""}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-2 space-y-4">
            {groups.map((group) => (
              <div key={group.key}>
                <h4 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {group.label} ({group.sources.length})
                </h4>
                <div className="space-y-2">
                  {group.sources.map((source, index) => (
                    <button
                      key={`${group.key}-${index}`}
                      type="button"
                      onClick={() => setSelectedSource(source)}
                      className="flex w-full items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-colors hover:border-[#652bb0]/30 hover:bg-[#652bb0]/5 dark:hover:border-[#652bb0]/40 dark:hover:bg-[#652bb0]/10"
                    >
                      <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#652bb0]/10 dark:bg-[#652bb0]/20">
                        <FileText className="size-4 text-[#652bb0] dark:text-[#652bb0]" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">
                          {formatJurisprudenceRef(source) || source.document_name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {source.source_type_label}
                          {source.solution ? ` · ${source.solution}` : ""}
                          {source.publication ? ` · ${source.publication}` : ""}
                        </p>
                      </div>
                      <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
                    </button>
                  ))}
                </div>
              </div>
            ))}

            <Collapsible open={isHelpOpen} onOpenChange={setIsHelpOpen}>
              <CollapsibleTrigger className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
                <HelpCircle className="size-3.5" />
                Comment sont classées les sources ?
              </CollapsibleTrigger>
              <CollapsibleContent className="px-1 pt-2 text-xs leading-relaxed text-muted-foreground">
                <p className="mb-2">
                  Les sources sont regroupées par catégorie de norme juridique :
                </p>
                <ul className="mb-2 list-disc space-y-1 pl-4">
                  <li>
                    <strong>Textes légaux et réglementaires</strong> : Code du
                    travail (parties législative et réglementaire), autres
                    codes, lois, décrets, traités.
                  </li>
                  <li>
                    <strong>Jurisprudence</strong> : décisions de Cour de
                    cassation, cour d&apos;appel, Conseil d&apos;État, Conseil
                    constitutionnel — triées par date (la plus récente en
                    premier).
                  </li>
                  <li>
                    <strong>Conventions collectives et accords</strong> : votre
                    CCN, accords de branche et d&apos;entreprise.
                  </li>
                  <li>
                    <strong>Sources internes</strong> : règlement intérieur,
                    contrats, décisions unilatérales, usages.
                  </li>
                </ul>
                <p>
                  À l&apos;intérieur de chaque catégorie, les sources sont classées
                  par pertinence. La catégorie est choisie selon la nature
                  juridique du document, pas selon la hiérarchie des normes —
                  plusieurs parties du Code du travail (législative et
                  réglementaire) apparaissent donc ensemble.
                </p>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </CollapsibleContent>
      </Collapsible>

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
                  {selectedSource && (formatJurisprudenceRef(selectedSource) || selectedSource.document_name)}
                </DialogTitle>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0] hover:bg-[#652bb0]/10 dark:bg-[#652bb0]/20 dark:text-[#652bb0] dark:hover:bg-[#652bb0]/20 text-xs">
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
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
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
                  {fullContentLoading
                    ? "Chargement…"
                    : "Voir le document complet"}
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
    </>
  );
}
