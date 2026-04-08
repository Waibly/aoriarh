"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { Badge } from "@/components/ui/badge";
import {
  ThumbsUp,
  ThumbsDown,
  Clock,
  DollarSign,
  Layers,
  FileSearch,
  BookOpen,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
} from "lucide-react";
import { InfoTooltip } from "@/components/admin/info-tooltip";

// ----------------- Shared types -----------------

export interface InspectChunk {
  document_id: string;
  doc_name: string;
  chunk_index: number;
  score: number;
  source_type: string;
  text_preview: string;
}

export interface RagTrace {
  query_original: string;
  query_condensed: string | null;
  variants: string[];
  identifiers_detected: { numero_pourvoi?: string[]; article_nums?: string[] };
  boost_injected: number;
  identifier_no_match?: boolean;
  hybrid_results: InspectChunk[];
  rerank_results: InspectChunk[];
  parent_groups: InspectChunk[];
  perf_ms: { [key: string]: number };
  model: string | null;
  out_of_scope: boolean;
  no_results: boolean;
  error: string | null;
}

export interface CitedSource {
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

/** Superset shape used by both the message inspector and the sandbox runner. */
export interface InspectorPayload {
  question: string;
  answer: string | null;
  sources: CitedSource[] | null;
  rag_trace: RagTrace | null;
  cost_usd: number | null;
  latency_ms: number | null;
  // Optional metadata (only present in real conversations)
  created_at?: string;
  user_email?: string | null;
  organisation_name?: string | null;
  feedback?: string | null;
  feedback_comment?: string | null;
}

// ----------------- Helpers -----------------

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

// ----------------- Sub-components -----------------

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

function CitedSourceItem({ source }: { source: CitedSource }) {
  const [open, setOpen] = useState(false);
  const meta = [
    source.juridiction,
    source.date_decision,
    source.numero_pourvoi && `n° ${source.numero_pourvoi}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="border rounded-md text-xs bg-muted/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full p-3 flex items-start justify-between gap-2 text-left hover:bg-muted/40 transition-colors"
      >
        <div className="flex items-start gap-2 min-w-0 flex-1">
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 mt-0.5 text-muted-foreground" />
          )}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="font-medium text-sm">{source.document_name}</div>
            {meta && <div className="text-muted-foreground text-[11px]">{meta}</div>}
            {source.article_nums && source.article_nums.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {source.article_nums.map((a) => (
                  <Badge key={a} variant="secondary" className="text-[10px] h-4">
                    Art. {a}
                  </Badge>
                ))}
              </div>
            )}
            {!open && source.excerpt && (
              <div className="text-muted-foreground line-clamp-2 mt-1">{source.excerpt}</div>
            )}
          </div>
        </div>
        <Badge variant="outline" className="text-[10px] h-5 shrink-0">
          {source.source_type_label || source.source_type} · niv. {source.norme_niveau}
        </Badge>
      </button>
      {open && source.full_text && (
        <div className="px-3 pb-3 pt-1 border-t bg-background/50">
          <div className="text-xs whitespace-pre-wrap text-foreground/90 leading-5 font-mono max-h-[600px] overflow-y-auto">
            {source.full_text}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  icon,
  children,
  help,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  help?: React.ReactNode;
}) {
  return (
    <div className="border-t pt-4">
      <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
        {icon}
        {title}
        {help && <InfoTooltip>{help}</InfoTooltip>}
      </h3>
      {children}
    </div>
  );
}

// ----------------- Main body component -----------------

export function InspectorBody({ data }: { data: InspectorPayload }) {
  return (
    <div className="space-y-4">
      {/* Métadonnées */}
      <div className="flex flex-wrap gap-2 text-xs">
        {data.user_email && <Badge variant="outline">{data.user_email}</Badge>}
        {data.organisation_name && <Badge variant="outline">{data.organisation_name}</Badge>}
        {data.created_at && (
          <Badge variant="outline">{new Date(data.created_at).toLocaleString("fr-FR")}</Badge>
        )}
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
          <Badge variant="outline" className="text-orange-600 border-orange-300">
            Hors-scope
          </Badge>
        )}
        <Badge variant="outline" className="font-mono">
          <DollarSign className="h-3 w-3 mr-1" />
          {fmtUsd(data.cost_usd)}
        </Badge>
        <Badge variant="outline" className="font-mono">
          <Clock className="h-3 w-3 mr-1" />
          {fmtMs(data.latency_ms)}
        </Badge>
        {data.rag_trace?.model && <Badge variant="outline">{data.rag_trace.model}</Badge>}
      </div>

      {/* Risk banner: identifier in query but no chunk matched */}
      {data.rag_trace?.identifier_no_match && (
        <div className="border border-orange-300 dark:border-orange-900 bg-orange-50 dark:bg-orange-950/30 rounded-md p-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-orange-600 dark:text-orange-400 mt-0.5 shrink-0" />
          <div className="text-xs text-orange-800 dark:text-orange-200">
            <div className="font-semibold mb-0.5">Risque d&apos;hallucination détecté</div>
            La question contient un identifiant explicite (article ou numéro de pourvoi)
            mais aucun chunk correspondant n&apos;a été trouvé dans le corpus indexé.
            La réponse ci-dessous a été générée à partir de chunks remontés
            <strong> par devinette sémantique du LLM d&apos;expansion</strong>, pas à partir de l&apos;identifiant demandé.
            Vérifiez que la réponse traite bien du sujet attendu.
          </div>
        </div>
      )}

      {/* Question */}
      <div>
        <h3 className="text-xs uppercase font-semibold text-muted-foreground mb-1">Question</h3>
        <div className="text-sm whitespace-pre-wrap">{data.question || "(non retrouvée)"}</div>
        {data.rag_trace?.query_condensed &&
          data.rag_trace.query_condensed !== data.question && (
            <div className="mt-2 text-xs text-muted-foreground">
              <span className="font-medium">Reformulée : </span>
              <span className="italic">{data.rag_trace.query_condensed}</span>
            </div>
          )}
      </div>

      {/* Réponse */}
      {data.answer && (
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
      )}

      {/* Sources citées */}
      {data.sources && data.sources.length > 0 && (
        <Section
          title={`Sources citées (${data.sources.length})`}
          icon={<BookOpen className="h-4 w-4" />}
          help={
            <>
              Documents que l&apos;utilisateur a vus dans le panneau Sources
              de sa réponse. Cliquez sur une source pour afficher son texte
              intégral tel qu&apos;il a été envoyé au LLM.
            </>
          }
        >
          <div className="space-y-2">
            {data.sources.map((s, i) => (
              <CitedSourceItem key={i} source={s} />
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
        <Section
          title="Performance"
          icon={<Clock className="h-4 w-4" />}
          help={
            <>
              Temps passé dans chaque étape du pipeline RAG.
              <br />• <strong>condense</strong> : reformulation multi-tour
              <br />• <strong>expand_search</strong> : génération des
              variantes + recherche hybride parallèle
              <br />• <strong>rerank</strong> : tri par cross-encoder
              <br />• <strong>parent_expansion</strong> : élargissement
              aux chunks frères
              <br />• <strong>generate</strong> : appel LLM final
            </>
          }
        >
          <PerfBar perf={data.rag_trace.perf_ms} />
        </Section>
      )}

      {/* Trace details */}
      {!data.rag_trace ? (
        <div className="border-t pt-4">
          <div className="text-xs text-muted-foreground italic">
            Trace non disponible (question antérieure à la mise en place du tracing).
          </div>
        </div>
      ) : (
        <>
          {data.rag_trace.variants.length > 0 && (
            <Section
              title="Reformulation pour la recherche"
              help={
                <>
                  Variantes de la question utilisées pour la recherche.
                  La <strong>1ère est la question originale</strong> (recherche
                  texte exact via BM25). Les suivantes sont générées par un
                  petit LLM pour couvrir l&apos;intention sémantique, la
                  terminologie juridique et des mots-clés.
                </>
              }
            >
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

          {(data.rag_trace.identifiers_detected.numero_pourvoi?.length ||
            data.rag_trace.identifiers_detected.article_nums?.length) ? (
            <Section
              title="Identifiants détectés dans la query"
              help={
                <>
                  Numéros d&apos;article ou de pourvoi trouvés dans la
                  question via regex. Pour ces identifiants, on cherche
                  directement dans Qdrant via filtre payload (boost) pour
                  garantir que les chunks correspondants remontent, même
                  si leur contenu est sémantiquement éloigné de la query.
                </>
              }
            >
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

          <Section
            title={`Sources finales envoyées au LLM (${data.rag_trace.parent_groups.length})`}
            icon={<Layers className="h-4 w-4" />}
            help={
              <>
                Liste finale des chunks que le LLM a réellement reçus pour
                rédiger sa réponse, après élargissement aux chunks frères
                (small-to-big). Chaque ligne représente un parent group
                (souvent plusieurs chunks fusionnés en un seul contexte).
              </>
            }
          >
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

          <Section
            title={`Chunks après rerank (${data.rag_trace.rerank_results.length})`}
            icon={<FileSearch className="h-4 w-4" />}
            help={
              <>
                Top chunks après tri par cross-encoder Voyage rerank-2.
                Le rerank prend les ~30 candidats du pool initial et les
                trie selon la pertinence réelle (modèle plus précis mais
                plus coûteux que la recherche initiale).
              </>
            }
          >
            <div className="space-y-2">
              {data.rag_trace.rerank_results.map((c, i) => (
                <ChunkRow key={`r-${c.document_id}-${c.chunk_index}-${i}`} chunk={c} rank={i + 1} />
              ))}
            </div>
          </Section>

          <Section
            title={`Pool initial avant rerank (${data.rag_trace.hybrid_results.length})`}
            help={
              <>
                Candidats remontés par la recherche hybride (dense Voyage
                law-2 + sparse BM25, fusion RRF), avant le rerank. C&apos;est
                à cette étape que tu vois si le bon document a au moins
                été trouvé par le moteur de recherche.
              </>
            }
          >
            <div className="space-y-2">
              {data.rag_trace.hybrid_results.map((c, i) => (
                <ChunkRow key={`h-${c.document_id}-${c.chunk_index}-${i}`} chunk={c} rank={i + 1} />
              ))}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
