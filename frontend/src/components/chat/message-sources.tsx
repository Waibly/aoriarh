"use client";

import { useState } from "react";
import { ChevronRight, FileText, HelpCircle } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  formatJurisprudenceRef,
  useSourceViewer,
} from "@/components/chat/source-viewer-context";
import { groupSources } from "@/lib/source-groups";
import type { MessageSource } from "@/types/api";

interface MessageSourcesProps {
  sources: MessageSource[];
}

export function MessageSources({ sources }: MessageSourcesProps) {
  const { openSource } = useSourceViewer();
  const [isOpen, setIsOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const groups = groupSources(sources);

  return (
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
        <div className="mt-3 space-y-7">
          {groups.map((group) => (
            <div key={group.key}>
              <h4 className="mb-3 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.label} ({group.sources.length})
              </h4>
              <div className="space-y-2">
                {group.sources.map((source, index) => (
                  <button
                    key={`${group.key}-${index}`}
                    type="button"
                    onClick={() => openSource(source)}
                    className="flex w-full items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-[#652bb0]/30 hover:bg-[#652bb0]/5 sm:gap-3 sm:px-4 sm:py-3 dark:hover:border-[#652bb0]/40 dark:hover:bg-[#652bb0]/10"
                  >
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#652bb0]/10 dark:bg-[#652bb0]/20">
                      <FileText className="size-4 text-[#652bb0] dark:text-[#652bb0]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-foreground">
                        {formatJurisprudenceRef(source) || source.document_name}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
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
                  travail (parties législative et réglementaire), autres codes,
                  lois, décrets, traités.
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
  );
}
