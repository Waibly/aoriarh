"use client";

import { useState } from "react";
import { ChevronRight, FileText } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useSourceViewer } from "@/components/chat/source-viewer-context";
import { sourceDate, sourceIdcc } from "@/lib/source-evidence";
import type { MessageSource } from "@/types/api";

interface MessageSourcesProps {
  sources: MessageSource[];
}

export function MessageSources({ sources }: MessageSourcesProps) {
  const { openSource } = useSourceViewer();
  const [isOpen, setIsOpen] = useState(false);

  if (sources.length === 0) {
    return (
      <p className="text-muted-foreground mt-4 text-xs">
        Aucun document source joint à cette réponse.
      </p>
    );
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring mt-4 flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none">
        <ChevronRight
          aria-hidden="true"
          className={`size-4 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
        />
        <FileText aria-hidden="true" className="size-4" />
        Sources · {sources.length}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-3 space-y-2">
          {sources.map((source, index) => {
            const date = sourceDate(source);
            const idcc = sourceIdcc(source);

            return (
              <li key={`${source.document_id}-${index}`}>
                <button
                  type="button"
                  onClick={() => openSource(source)}
                  className="border-border bg-card hover:border-primary/30 hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring flex w-full items-center gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none sm:gap-3 sm:px-4 sm:py-3"
                >
                  <span className="bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-md">
                    <FileText aria-hidden="true" className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="text-foreground block text-sm font-medium break-words">
                      {source.document_name}
                    </span>
                    <span className="text-muted-foreground flex flex-wrap gap-x-2 gap-y-1 text-xs">
                      <span>{source.source_type_label}</span>
                      {idcc && <span>IDCC {idcc}</span>}
                      {date && <span>{date}</span>}
                    </span>
                  </span>
                  <ChevronRight
                    aria-hidden="true"
                    className="text-muted-foreground size-4 shrink-0"
                  />
                </button>
              </li>
            );
          })}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}
