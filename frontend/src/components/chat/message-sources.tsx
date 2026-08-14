"use client";

import { useMemo, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  FileText,
  HelpCircle,
  Quote,
  Search,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
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
import {
  partitionSources,
  sourceDate,
  sourceIdcc,
  type SourceEvidence,
} from "@/lib/source-evidence";
import type { MessageSource } from "@/types/api";

interface MessageSourcesProps {
  sources: MessageSource[];
  answer?: string;
}

export function MessageSources({ sources, answer = "" }: MessageSourcesProps) {
  const { openSource } = useSourceViewer();
  const [isOpen, setIsOpen] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const { foundations, consulted } = useMemo(
    () => partitionSources(answer, sources),
    [answer, sources],
  );
  const consultedGroups = groupSources(consulted);

  const foundationLabel = `${foundations.length} fondement${foundations.length > 1 ? "s" : ""}`;
  const consultedLabel = `${consulted.length} autre${consulted.length > 1 ? "s" : ""} document${consulted.length > 1 ? "s" : ""}`;

  const renderFoundation = ({ source, references }: SourceEvidence) => {
    const idcc = sourceIdcc(source);
    const date = sourceDate(source);

    return (
      <button
        key={source.document_id}
        type="button"
        onClick={() => openSource(source)}
        className="w-full rounded-xl border border-[#652bb0]/25 bg-[#652bb0]/5 p-4 text-left transition-colors hover:border-[#652bb0]/45 hover:bg-[#652bb0]/10 dark:border-[#652bb0]/35 dark:bg-[#652bb0]/10 dark:hover:bg-[#652bb0]/15"
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-[#652bb0]/15">
            <CheckCircle2 className="size-4.5 text-[#652bb0]" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-foreground text-sm font-semibold">
              {references.slice(0, 3).join(" · ")}
              {references.length > 3 ? ` · +${references.length - 3}` : ""}
            </p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {formatJurisprudenceRef(source) || source.document_name}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge variant="outline" className="rounded-full text-[11px]">
                {source.source_type_label}
              </Badge>
              {idcc && (
                <Badge variant="outline" className="rounded-full text-[11px]">
                  IDCC {idcc}
                </Badge>
              )}
              {date && (
                <Badge
                  variant="outline"
                  className="gap-1 rounded-full text-[11px]"
                >
                  <CalendarDays className="size-3" />
                  {date}
                </Badge>
              )}
              <Badge variant="outline" className="rounded-full text-[11px]">
                {source.legal_status ||
                  (source.corpus_status === "available_at_answer_time"
                    ? "Disponible lors de la réponse"
                    : "Consulté lors de la réponse")}
              </Badge>
            </div>
            {source.excerpt && (
              <div className="border-border/70 bg-background/80 mt-3 flex gap-2 rounded-lg border px-3 py-2.5">
                <Quote className="mt-0.5 size-3.5 shrink-0 text-[#652bb0]" />
                <p className="text-muted-foreground line-clamp-3 text-xs leading-relaxed">
                  {source.excerpt}
                </p>
              </div>
            )}
            <p className="mt-2 flex items-center gap-1 text-xs font-medium text-[#652bb0]">
              Ouvrir le passage
              <ChevronRight className="size-3.5" />
            </p>
          </div>
        </div>
      </button>
    );
  };

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger className="mt-4 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-[#652bb0] transition-colors hover:bg-[#652bb0]/5 dark:text-[#652bb0] dark:hover:bg-[#652bb0]/10">
        <ChevronRight
          className={`size-4 transition-transform duration-200 ${isOpen ? "rotate-90" : ""}`}
        />
        <FileText className="size-4" />
        {foundations.length > 0
          ? consulted.length > 0
            ? `${foundationLabel} · ${consultedLabel}`
            : foundationLabel
          : `${sources.length} document${sources.length > 1 ? "s" : ""} consulté${sources.length > 1 ? "s" : ""}`}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-3 space-y-8">
          {foundations.length > 0 && (
            <section>
              <div className="mb-3 px-1">
                <h4 className="text-foreground flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
                  <CheckCircle2 className="size-3.5 text-[#652bb0]" />
                  Fondements utilisés dans la réponse ({foundations.length})
                </h4>
                <p className="text-muted-foreground mt-1 text-xs">
                  Références explicitement reliées au texte de la réponse.
                </p>
              </div>
              <div className="space-y-3">
                {foundations.map(renderFoundation)}
              </div>
            </section>
          )}

          {consulted.length > 0 && (
            <section>
              <div className="mb-3 px-1">
                <h4 className="text-muted-foreground flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
                  <Search className="size-3.5" />
                  {foundations.length > 0
                    ? `Autres documents consultés (${consulted.length})`
                    : `Documents consultés (${consulted.length})`}
                </h4>
                {foundations.length === 0 && (
                  <p className="text-muted-foreground mt-1 text-xs">
                    Aucune référence n’a pu être reliée automatiquement avec
                    certitude ; aucun document n’est masqué.
                  </p>
                )}
              </div>
              <div className="space-y-7">
                {consultedGroups.map((group) => (
                  <div key={group.key}>
                    <h4 className="text-muted-foreground mb-3 px-1 text-xs font-semibold tracking-wide uppercase">
                      {group.label} ({group.sources.length})
                    </h4>
                    <div className="space-y-2">
                      {group.sources.map((source, index) => (
                        <button
                          key={`${group.key}-${index}`}
                          type="button"
                          onClick={() => openSource(source)}
                          className="border-border bg-card flex w-full items-center gap-2 rounded-lg border px-3 py-2.5 text-left transition-colors hover:border-[#652bb0]/30 hover:bg-[#652bb0]/5 sm:gap-3 sm:px-4 sm:py-3 dark:hover:border-[#652bb0]/40 dark:hover:bg-[#652bb0]/10"
                        >
                          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-[#652bb0]/10 dark:bg-[#652bb0]/20">
                            <FileText className="size-4 text-[#652bb0] dark:text-[#652bb0]" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="text-foreground truncate text-sm font-medium">
                              {formatJurisprudenceRef(source) ||
                                source.document_name}
                            </p>
                            <p className="text-muted-foreground truncate text-xs">
                              {source.source_type_label}
                              {source.solution ? ` · ${source.solution}` : ""}
                              {source.publication
                                ? ` · ${source.publication}`
                                : ""}
                            </p>
                          </div>
                          <ChevronRight className="text-muted-foreground size-4 shrink-0" />
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <Collapsible open={isHelpOpen} onOpenChange={setIsHelpOpen}>
            <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 px-1 text-xs transition-colors">
              <HelpCircle className="size-3.5" />
              Comment sont classées les sources ?
            </CollapsibleTrigger>
            <CollapsibleContent className="text-muted-foreground px-1 pt-2 text-xs leading-relaxed">
              <p className="mb-2">
                Un document devient un <strong>fondement utilisé</strong>{" "}
                uniquement lorsqu’une référence de la réponse — article,
                décision, texte daté ou nom exact — peut être reliée avec
                certitude à ce document. Les autres restent visibles afin de ne
                jamais masquer une source que l’assistant aurait utilisée sans
                la citer explicitement.
              </p>
              <p className="mb-2">
                Les autres documents sont regroupés par catégorie juridique :
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
                À l&apos;intérieur de chaque catégorie, les sources sont
                classées par pertinence. La catégorie est choisie selon la
                nature juridique du document, pas selon la hiérarchie des normes
                — plusieurs parties du Code du travail (législative et
                réglementaire) apparaissent donc ensemble.
              </p>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
