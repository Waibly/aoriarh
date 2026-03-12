"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { ChevronRight, FileText } from "lucide-react";
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
  const [isOpen, setIsOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState<MessageSource | null>(
    null,
  );

  return (
    <>
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger className="mt-4 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-[#9952b8] transition-colors hover:bg-[#9952b8]/5 dark:text-[#9952b8] dark:hover:bg-[#9952b8]/10">
          <ChevronRight
            className={`size-4 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
          />
          <FileText className="size-4" />
          {sources.length} source{sources.length > 1 ? "s" : ""} consultée
          {sources.length > 1 ? "s" : ""}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="mt-2 space-y-2">
            {sources.map((source, index) => (
              <button
                key={index}
                type="button"
                onClick={() => setSelectedSource(source)}
                className="flex w-full items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-left transition-colors hover:border-[#9952b8]/30 hover:bg-[#9952b8]/5 dark:hover:border-[#9952b8]/40 dark:hover:bg-[#9952b8]/10"
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#9952b8]/10 dark:bg-[#9952b8]/20">
                  <FileText className="size-4 text-[#9952b8] dark:text-[#9952b8]" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">
                    {formatJurisprudenceRef(source) || source.document_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {source.source_type_label} · Niveau {source.norme_niveau}
                    {source.solution ? ` · ${source.solution}` : ""}
                    {source.publication ? ` · ${source.publication}` : ""}
                  </p>
                </div>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </button>
            ))}
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
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[#9952b8]/10 dark:bg-[#9952b8]/20">
                <FileText className="size-5 text-[#9952b8] dark:text-[#9952b8]" />
              </div>
              <div className="min-w-0">
                <DialogTitle className="truncate text-base">
                  {selectedSource && (formatJurisprudenceRef(selectedSource) || selectedSource.document_name)}
                </DialogTitle>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8] hover:bg-[#9952b8]/10 dark:bg-[#9952b8]/20 dark:text-[#9952b8] dark:hover:bg-[#9952b8]/20 text-xs">
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
            <div className="prose prose-sm dark:prose-invert max-w-none pr-4 text-[0.9375rem] leading-7 text-foreground [&_h1]:mt-6 [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:text-[0.9375rem] [&_h3]:font-semibold [&_p]:my-3 [&_p]:leading-7 [&_ul]:my-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_li]:leading-7 [&_li::marker]:text-foreground/70 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                {selectedSource?.full_text || selectedSource?.excerpt || ""}
              </ReactMarkdown>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
