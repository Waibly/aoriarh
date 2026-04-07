"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { apiFetch } from "@/lib/api";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { ThumbsUp, ThumbsDown, Clock, DollarSign, Layers, FileSearch, BookOpen } from "lucide-react";

interface InspectChunk {
  document_id: string;
  doc_name: string;
  chunk_index: number;
  score: number;
  source_type: string;
  text_preview: string;
}

interface RagTrace {
  query_original: string;
  query_condensed: string | null;
  variants: string[];
  identifiers_detected: { numero_pourvoi?: string[]; article_nums?: string[] };
  boost_injected: number;
  hybrid_results: InspectChunk[];
  rerank_results: InspectChunk[];
  parent_groups: InspectChunk[];
  perf_ms: { [key: string]: number };
  model: string | null;
  out_of_scope: boolean;
  no_results: boolean;
  error: string | null;
}

interface CitedSource {
  document_name: string;
  source_type: string;
  source_type_label: string;
  norme_niveau: number;
  excerpt: string;
  full_text: string;
  juridiction?: string | null;
  numero_pourvoi?: string | null;
  date_decision?: string | null;
  article_nums?: string[] | null;
}

interface MessageInspect {
  message_id: string;
  conversation_id: string;
  created_at: string;
  user_email: string | null;
  organisation_name: string | null;
  question: string;
  answer: string;
  sources: CitedSource[] | null;
  feedback: string | null;
  feedback_comment: string | null;
  cost_usd: number | null;
  latency_ms: number | null;
  rag_trace: RagTrace | null;
}

function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function fmtUsd(usd: number | null): string {
  if (usd === null || usd === undefined) return "—";
  if (usd < 0.01) return `${(usd * 1000).toFixed(2)} m$`;
  return `$${usd.toFixed(4)}`;
}

function PerfBar({ perf }: { perf: { [key: string]: number } }) {
  const stages = ["condense", "expand_search", "rerank", "parent_expansion", "generate"];
  const colors: { [key: string]: string } = {
    condense: "bg-blue-500",
    expand_search: "bg-purple-500",
    rerank: "bg-amber-500",
    parent_expansion: "bg-cyan-500",
    generate: "bg-green-500",
  };
  const present = stages.filter((s) => perf[s] !== undefined);
  const total = present.reduce((acc, s) => acc + perf[s], 0);
  if (total === 0) return <div className="text-xs text-muted-foreground">Pas de données de performance</div>;
  return (
    <div className="space-y-2">
      <div className="flex w-full h-6 rounded-md overflow-hidden border">
        {present.map((s) => (
          <div
            key={s}
            className={colors[s]}
            style={{ width: `${(perf[s] / total) * 100}%` }}
            title={`${s}: ${fmtMs(perf[s])}`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-xs">
        {present.map((s) => (
          <div key={s} className="flex items-center gap-1">
            <div className={`w-3 h-3 rounded-sm ${colors[s]}`} />
            <span className="text-muted-foreground">{s}</span>
            <span className="font-medium">{fmtMs(perf[s])}</span>
          </div>
        ))}
        <div className="flex items-center gap-1 ml-auto font-semibold">
          <Clock className="h-3 w-3" />
          Total : {fmtMs(perf.total ?? total)}
        </div>
      </div>
    </div>
  );
}

function ChunkRow({ chunk, rank }: { chunk: InspectChunk; rank: number }) {
  return (
    <div className="border rounded-md p-2 text-xs space-y-1 bg-muted/20">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-muted-foreground font-mono shrink-0">#{rank}</span>
          <span className="font-medium truncate">{chunk.doc_name}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Badge variant="outline" className="text-[10px] h-5">
            chunk {chunk.chunk_index}
          </Badge>
          <span className="font-mono text-muted-foreground">{chunk.score.toFixed(3)}</span>
        </div>
      </div>
      <div className="text-muted-foreground line-clamp-2">{chunk.text_preview}</div>
    </div>
  );
}

function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="border-t pt-4">
      <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
        {icon}
        {title}
      </h3>
      {children}
    </div>
  );
}

export function ConversationInspector({
  messageId,
  open,
  onOpenChange,
}: {
  messageId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: session } = useSession();
  const [data, setData] = useState<MessageInspect | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!messageId || !session?.access_token) return;
    setLoading(true);
    setData(null);
    apiFetch<MessageInspect>(
      `/admin/quality/messages/${messageId}/inspect`,
      { token: session.access_token },
    )
      .then((d) => setData(d))
      .catch((err) => {
        console.error(err);
        toast.error("Impossible de charger le détail du message");
      })
      .finally(() => setLoading(false));
  }, [messageId, session?.access_token]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="sm:max-w-3xl w-full overflow-hidden flex flex-col p-0">
        <SheetHeader className="px-6 pt-6 pb-2">
          <SheetTitle>Inspection du message</SheetTitle>
          <SheetDescription>
            Trace complète du pipeline RAG pour cette question.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading || !data ? (
            <div className="space-y-3 px-6 py-4">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : (
            <div className="space-y-4 px-6 py-4">
              {/* Métadonnées */}
              <div className="flex flex-wrap gap-2 text-xs">
                {data.user_email && <Badge variant="outline">{data.user_email}</Badge>}
                {data.organisation_name && <Badge variant="outline">{data.organisation_name}</Badge>}
                <Badge variant="outline">{new Date(data.created_at).toLocaleString("fr-FR")}</Badge>
                {data.feedback === "up" && (
                  <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-0">
                    <ThumbsUp className="h-3 w-3 mr-1" /> Positif
                  </Badge>
                )}
                {data.feedback === "down" && (
                  <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-0">
                    <ThumbsDown className="h-3 w-3 mr-1" /> Négatif
                  </Badge>
                )}
                {data.rag_trace?.out_of_scope && (
                  <Badge variant="outline" className="text-orange-600 border-orange-300">Hors-scope</Badge>
                )}
              </div>

              {/* Question */}
              <div>
                <h3 className="text-xs uppercase font-semibold text-muted-foreground mb-1">Question</h3>
                <div className="text-sm whitespace-pre-wrap">{data.question || "(non retrouvée)"}</div>
                {data.rag_trace?.query_condensed && data.rag_trace.query_condensed !== data.question && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    <span className="font-medium">Reformulée : </span>
                    <span className="italic">{data.rag_trace.query_condensed}</span>
                  </div>
                )}
              </div>

              {/* Réponse */}
              <div>
                <h3 className="text-xs uppercase font-semibold text-muted-foreground mb-1">Réponse</h3>
                <div className="bg-muted/30 rounded-md p-4">
                  <div className="prose prose-sm dark:prose-invert max-w-none text-[0.875rem] leading-6 [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-base [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_p]:my-2 [&_ul]:my-2 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:my-2 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:my-0.5 [&_strong]:font-semibold [&_table]:my-3 [&_table]:border [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:px-2 [&_td]:py-1 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
                      {data.answer}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>

              {/* Sources citées (toujours affichées si présentes) */}
              {data.sources && data.sources.length > 0 && (
                <Section title={`Sources citées (${data.sources.length})`} icon={<BookOpen className="h-4 w-4" />}>
                  <div className="space-y-2">
                    {data.sources.map((s, i) => (
                      <div key={i} className="border rounded-md p-3 text-xs space-y-1 bg-muted/20">
                        <div className="flex items-start justify-between gap-2">
                          <div className="font-medium text-sm">{s.document_name}</div>
                          <Badge variant="outline" className="text-[10px] h-5 shrink-0">
                            {s.source_type_label || s.source_type} · niv. {s.norme_niveau}
                          </Badge>
                        </div>
                        {(s.juridiction || s.numero_pourvoi || s.date_decision) && (
                          <div className="text-muted-foreground text-[11px]">
                            {[s.juridiction, s.date_decision, s.numero_pourvoi && `n° ${s.numero_pourvoi}`]
                              .filter(Boolean)
                              .join(" · ")}
                          </div>
                        )}
                        {s.article_nums && s.article_nums.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {s.article_nums.map((a) => (
                              <Badge key={a} variant="secondary" className="text-[10px] h-4">
                                Art. {a}
                              </Badge>
                            ))}
                          </div>
                        )}
                        {s.excerpt && (
                          <div className="text-muted-foreground line-clamp-3 mt-1">{s.excerpt}</div>
                        )}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {data.feedback_comment && (
                <div>
                  <h3 className="text-xs uppercase font-semibold text-muted-foreground mb-1">
                    Commentaire utilisateur
                  </h3>
                  <div className="text-sm bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-900 rounded-md p-3">
                    {data.feedback_comment}
                  </div>
                </div>
              )}

              {/* Performance */}
              {data.rag_trace && Object.keys(data.rag_trace.perf_ms || {}).length > 0 && (
                <Section title="Performance" icon={<Clock className="h-4 w-4" />}>
                  <PerfBar perf={data.rag_trace.perf_ms} />
                </Section>
              )}

              {/* Coût */}
              <Section title="Coût" icon={<DollarSign className="h-4 w-4" />}>
                <div className="text-sm">
                  <span className="font-bold">{fmtUsd(data.cost_usd)}</span>
                  {data.rag_trace?.model && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      via {data.rag_trace.model}
                    </span>
                  )}
                </div>
              </Section>

              {/* Trace details */}
              {!data.rag_trace ? (
                <div className="border-t pt-4">
                  <div className="text-xs text-muted-foreground italic">
                    Trace non disponible (question antérieure à la mise en place du tracing).
                  </div>
                </div>
              ) : (
                <>
                  {/* Variants */}
                  {data.rag_trace.variants.length > 0 && (
                    <Section title="Reformulation pour la recherche">
                      <ol className="space-y-1 text-xs">
                        {data.rag_trace.variants.map((v, i) => (
                          <li key={i} className="flex gap-2">
                            <span className="text-muted-foreground font-mono">{i + 1}.</span>
                            <span>{v}</span>
                          </li>
                        ))}
                      </ol>
                    </Section>
                  )}

                  {/* Identifiers */}
                  {(data.rag_trace.identifiers_detected.numero_pourvoi?.length ||
                    data.rag_trace.identifiers_detected.article_nums?.length) ? (
                    <Section title="Identifiants détectés dans la query">
                      <div className="flex flex-wrap gap-2">
                        {data.rag_trace.identifiers_detected.numero_pourvoi?.map((p) => (
                          <Badge key={p} variant="secondary">Pourvoi {p}</Badge>
                        ))}
                        {data.rag_trace.identifiers_detected.article_nums?.map((a) => (
                          <Badge key={a} variant="secondary">Article {a}</Badge>
                        ))}
                        {data.rag_trace.boost_injected > 0 && (
                          <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-0">
                            +{data.rag_trace.boost_injected} chunks injectés
                          </Badge>
                        )}
                      </div>
                    </Section>
                  ) : null}

                  {/* Parent groups */}
                  <Section title={`Sources finales envoyées au LLM (${data.rag_trace.parent_groups.length})`}
                    icon={<Layers className="h-4 w-4" />}>
                    <div className="space-y-2">
                      {data.rag_trace.parent_groups.length === 0 ? (
                        <div className="text-xs text-muted-foreground">Aucune source remontée</div>
                      ) : (
                        data.rag_trace.parent_groups.map((c, i) => (
                          <ChunkRow key={`${c.document_id}-${c.chunk_index}`} chunk={c} rank={i + 1} />
                        ))
                      )}
                    </div>
                  </Section>

                  {/* Reranked chunks */}
                  <Section title={`Chunks après rerank (${data.rag_trace.rerank_results.length})`}
                    icon={<FileSearch className="h-4 w-4" />}>
                    <div className="space-y-2">
                      {data.rag_trace.rerank_results.map((c, i) => (
                        <ChunkRow key={`r-${c.document_id}-${c.chunk_index}-${i}`} chunk={c} rank={i + 1} />
                      ))}
                    </div>
                  </Section>

                  {/* Hybrid pool */}
                  <Section title={`Pool initial avant rerank (${data.rag_trace.hybrid_results.length})`}>
                    <div className="space-y-2">
                      {data.rag_trace.hybrid_results.map((c, i) => (
                        <ChunkRow key={`h-${c.document_id}-${c.chunk_index}-${i}`} chunk={c} rank={i + 1} />
                      ))}
                    </div>
                  </Section>
                </>
              )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
