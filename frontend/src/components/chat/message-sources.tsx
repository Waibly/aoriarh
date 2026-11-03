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
        <ul className="border-border mt-2 divide-y overflow-hidden rounded-lg border">
          {sources.map((source, index) => {
            const date = sourceDate(source);
            const idcc = sourceIdcc(source);

            return (
              <li key={`${source.document_id}-${index}`}>
                <button
                  type="button"
                  onClick={() => openSource(source)}
                  className="hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring flex w-full items-center gap-3 px-3 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset sm:px-4"
                >
                  <FileText
                    aria-hidden="true"
                    className="text-muted-foreground size-4 shrink-0"
                  />
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
