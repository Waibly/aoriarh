"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSourceFullContent } from "@/lib/chat-api";
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
  Loader2,
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

export interface SearchPlanTrace {
  version: string;
  query_original: string;
  standalone_question: string;
  mode:
    | "exact_reference"
    | "legal_news"
    | "source_directed"
    | "follow_up"
    | "standard";
  answer_intent: string;
  answer_format: string;
  query_budget?: number;
  needs_llm_planner: boolean;
  needs_condensation: boolean;
  explicit_identifiers: { numero_pourvoi?: string[]; article_nums?: string[] };
  requested_source_types: string[];
  applicable_idccs: string[];
  time_scope: {
    kind: string;
    days?: number;
    year?: number;
    source: string;
  } | null;
  legislation: string;
  ccn: string;
  jurisprudence: string;
  internal_documents: string;
  planner_status: "not_needed" | "pending" | "ok" | "fallback";
  legal_topics: string[];
  search_queries: string[];
  hypothesized_articles: { reference: string; confidence: string }[];
  missing_facts: string[];
  planner_source_hints: string[];
  planner_jurisprudence: string | null;
  planner_answer_intent: string | null;
  reasons: string[];
  warnings: string[];
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
  search_plan?: SearchPlanTrace | null;
  search_plan_usage?: {
    model?: string;
    prompt_tokens?: number;
    completion_tokens?: number;
    cost_usd?: number;
    latency_ms?: number;
    execution?: "observation_only" | "adaptive_shadow";
    fallback_to_baseline?: boolean;
  };
  error: string | null;
}

export interface CitedSource {
  document_id?: string;
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

export interface OrgCcnInfo {
  idcc: string;
  titre: string | null;
  status: string;
  use_custom: boolean;
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
  user_profil_metier?: string | null;
  organisation_name?: string | null;
  organisation_id?: string | null;
  org_forme_juridique?: string | null;
  org_taille?: string | null;
  org_secteur_activite?: string | null;
  org_convention_collective?: string | null;
  org_idccs?: OrgCcnInfo[];
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
  const stages = [
    "condense",
    "expand_search",
    "rerank",
    "parent_expansion",
    "generate",
  ];
  const colors: { [key: string]: string } = {
    condense: "bg-blue-500",
    expand_search: "bg-purple-500",
    rerank: "bg-amber-500",
    parent_expansion: "bg-cyan-500",
    generate: "bg-green-500",
  };
  const present = stages.filter((s) => perf[s] !== undefined);
  const total = present.reduce((acc, s) => acc + perf[s], 0);
  if (total === 0)
    return (
      <div className="text-muted-foreground text-xs">
        Pas de données de performance
      </div>
    );
  return (
    <div className="space-y-2">
      <div className="flex h-6 w-full overflow-hidden rounded-md border">
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
            <div className={`h-3 w-3 rounded-sm ${colors[s]}`} />
            <span className="text-muted-foreground">{s}</span>
            <span className="font-medium">{fmtMs(perf[s])}</span>
          </div>
        ))}
        <div className="ml-auto flex items-center gap-1 font-semibold">
          <Clock className="h-3 w-3" />
          Total : {fmtMs(perf.total ?? total)}
        </div>
      </div>
    </div>
  );
}

function SearchPlanPanel({
  plan,
  usage,
}: {
  plan: SearchPlanTrace;
  usage?: RagTrace["search_plan_usage"];
}) {
  const modeLabels: Record<SearchPlanTrace["mode"], string> = {
    exact_reference: "Référence exacte",
    legal_news: "Actualités juridiques",
    source_directed: "Source demandée",
    follow_up: "Relance conversationnelle",
    standard: "Question juridique standard",
  };
  const statusLabels: Record<SearchPlanTrace["planner_status"], string> = {
    not_needed: "Plan déterministe suffisant",
    pending: "Plan déterministe uniquement",
    ok: "Simulation compacte réussie",
    fallback: "Repli sur le plan déterministe",
  };
  const requirements = [
    ["Législation", plan.legislation],
    ["CCN", plan.ccn],
    ["Jurisprudence", plan.jurisprudence],
    ["Documents internes", plan.internal_documents],
  ];
  const references = [
    ...(plan.explicit_identifiers.article_nums ?? []).map(
      (ref) => `Article ${ref}`
    ),
    ...(plan.explicit_identifiers.numero_pourvoi ?? []).map(
      (ref) => `Pourvoi ${ref}`
    ),
  ];
  const adaptiveExecuted = usage?.execution === "adaptive_shadow";

  return (
    <Section
      title={
        adaptiveExecuted
          ? "Plan de recherche (exécuté dans le sandbox)"
          : "Plan de recherche (observation)"
      }
      icon={<FileSearch className="h-4 w-4" />}
      help={
        <>
          {adaptiveExecuted
            ? "Ce plan a piloté cette exécution du sandbox uniquement. Le chat client utilise toujours le pipeline actuel."
            : "Ce plan est comparé au pipeline actuel mais ne pilote pas cette recherche. En production, seuls les signaux déterministes sont enregistrés."}
        </>
      }
    >
      <div className="space-y-3 rounded-md border bg-blue-50/50 p-3 text-xs dark:bg-blue-950/20">
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{modeLabels[plan.mode]}</Badge>
          <Badge variant="outline">{statusLabels[plan.planner_status]}</Badge>
          <Badge variant="outline">Réponse : {plan.answer_intent}</Badge>
          {plan.query_budget !== undefined && (
            <Badge variant="outline">
              {plan.query_budget} requête{plan.query_budget > 1 ? "s" : ""}{" "}
              enrichie
            </Badge>
          )}
          {adaptiveExecuted && <Badge>Exécuté dans ce sandbox</Badge>}
          {usage?.fallback_to_baseline && (
            <Badge variant="destructive">Repli sur le pipeline actuel</Badge>
          )}
          {plan.needs_condensation && (
            <Badge variant="outline">Condensation nécessaire</Badge>
          )}
        </div>

        {plan.standalone_question !== plan.query_original && (
          <div>
            <span className="text-muted-foreground">
              Question autonome proposée :{" "}
            </span>
            <span className="font-medium">{plan.standalone_question}</span>
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {requirements.map(([label, value]) => (
            <div
              key={label}
              className="bg-background rounded border px-2 py-1.5"
            >
              <div className="text-muted-foreground">{label}</div>
              <div className="font-medium">{value}</div>
            </div>
          ))}
        </div>

        {(plan.applicable_idccs.length > 0 || references.length > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {plan.applicable_idccs.map((idcc) => (
              <Badge key={idcc} variant="secondary">
                IDCC {idcc}
              </Badge>
            ))}
            {references.map((reference) => (
              <Badge key={reference} variant="secondary">
                {reference}
              </Badge>
            ))}
          </div>
        )}

        {plan.legal_topics.length > 0 && (
          <div>
            <div className="text-muted-foreground mb-1">Notions juridiques</div>
            <div className="flex flex-wrap gap-1.5">
              {plan.legal_topics.map((topic) => (
                <Badge key={topic} variant="outline">
                  {topic}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {plan.search_queries.length > 0 && (
          <div>
            <div className="text-muted-foreground mb-1">Requêtes proposées</div>
            <ol className="list-decimal space-y-1 pl-4">
              {plan.search_queries.map((query) => (
                <li key={query}>{query}</li>
              ))}
            </ol>
          </div>
        )}

        {plan.hypothesized_articles.length > 0 && (
          <div className="rounded border border-amber-200 bg-amber-50 p-2 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
            <div className="font-medium">Articles supposés — non utilisés</div>
            <div>
              {plan.hypothesized_articles
                .map(
                  (article) => `${article.reference} (${article.confidence})`
                )
                .join(" · ")}
            </div>
          </div>
        )}

        {plan.missing_facts.length > 0 && (
          <div>
            <span className="text-muted-foreground">Faits manquants : </span>
            {plan.missing_facts.join(" · ")}
          </div>
        )}

        {plan.warnings.length > 0 && (
          <div className="text-amber-700 dark:text-amber-300">
            Alertes : {plan.warnings.join(" · ")}
          </div>
        )}

        {usage && (usage.prompt_tokens || usage.latency_ms !== undefined) && (
          <div className="text-muted-foreground">
            Simulation : {usage.prompt_tokens ?? 0} tokens entrée ·{" "}
            {usage.completion_tokens ?? 0} sortie · {fmtMs(usage.latency_ms)} ·{" "}
            {fmtUsd(usage.cost_usd ?? null)}
          </div>
        )}
      </div>
    </Section>
  );
}

function ChunkRow({ chunk, rank }: { chunk: InspectChunk; rank: number }) {
  return (
    <div className="bg-muted/20 space-y-1 rounded-md border p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-muted-foreground shrink-0 font-mono">
            #{rank}
          </span>
          <span className="truncate font-medium">{chunk.doc_name}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" className="h-5 text-[10px]">
            chunk {chunk.chunk_index}
          </Badge>
          <span className="text-muted-foreground font-mono">
            {chunk.score.toFixed(3)}
          </span>
        </div>
      </div>
      <div className="text-muted-foreground line-clamp-2">
        {chunk.text_preview}
      </div>
    </div>
  );
}

function CitedSourceItem({ source }: { source: CitedSource }) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [open, setOpen] = useState(false);
  const [fullContent, setFullContent] = useState<string | null>(null);
  const [fullContentLoading, setFullContentLoading] = useState(false);
  const [fullContentError, setFullContentError] = useState<string | null>(null);

  // Reset when the source changes (e.g. re-run of the sandbox)
  useEffect(() => {
    setFullContent(null);
    setFullContentError(null);
  }, [source.document_id]);

  const displayedText = fullContent ?? source.full_text ?? "";
  const isTruncated =
    fullContent === null && source.full_text.trimEnd().endsWith("[…]");

  const handleLoadFullContent = async () => {
    if (!source.document_id || !token) return;
    setFullContentLoading(true);
    setFullContentError(null);
    try {
      const data = await getSourceFullContent(source.document_id, token);
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

  const meta = [
    source.juridiction,
    source.date_decision,
    source.numero_pourvoi && `n° ${source.numero_pourvoi}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="bg-muted/20 overflow-hidden rounded-md border text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="hover:bg-muted/40 flex w-full items-start justify-between gap-2 p-3 text-left transition-colors"
      >
        <div className="flex min-w-0 flex-1 items-start gap-2">
          {open ? (
            <ChevronDown className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
          )}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="text-sm font-medium">{source.document_name}</div>
            {meta && (
              <div className="text-muted-foreground text-[11px]">{meta}</div>
            )}
            {source.article_nums && source.article_nums.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {source.article_nums.map((a) => (
                  <Badge
                    key={a}
                    variant="secondary"
                    className="h-4 text-[10px]"
                  >
                    Art. {a}
                  </Badge>
                ))}
              </div>
            )}
            {!open && source.excerpt && (
              <div className="text-muted-foreground mt-1 line-clamp-2">
                {source.excerpt}
              </div>
            )}
          </div>
        </div>
        <Badge variant="outline" className="h-5 shrink-0 text-[10px]">
          {source.source_type_label || source.source_type} · niv.{" "}
          {source.norme_niveau}
        </Badge>
      </button>
      {open && source.full_text && (
        <div className="bg-background/50 border-t px-3 pt-1 pb-3">
          <div className="text-foreground/90 prose prose-xs dark:prose-invert prose-headings:my-2 prose-p:my-1 prose-table:text-[11px] prose-th:bg-muted prose-th:px-2 prose-th:py-1 prose-td:px-2 prose-td:py-1 prose-td:border prose-th:border max-h-[600px] max-w-none overflow-y-auto text-xs">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeSanitize]}
            >
              {displayedText}
            </ReactMarkdown>
          </div>
          {(isTruncated || fullContentError) && source.document_id && (
            <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
              <span
                className={
                  fullContentError
                    ? "text-destructive"
                    : "text-muted-foreground"
                }
              >
                {fullContentError ?? "Extrait tronqué pour la lisibilité."}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px]"
                onClick={handleLoadFullContent}
                disabled={fullContentLoading}
              >
                {fullContentLoading ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <BookOpen className="mr-1 h-3 w-3" />
                )}
                Voir le document complet
              </Button>
            </div>
          )}
          {fullContent !== null && (
            <div className="text-muted-foreground mt-2 text-center text-[11px]">
              Document complet affiché.
            </div>
          )}
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
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
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
        {data.organisation_name && (
          <Badge variant="outline">{data.organisation_name}</Badge>
        )}
        {data.created_at && (
          <Badge variant="outline">
            {new Date(data.created_at).toLocaleString("fr-FR")}
          </Badge>
        )}
        {data.feedback === "up" && (
          <Badge className="border-0 bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400">
            <ThumbsUp className="mr-1 h-3 w-3" /> Positif
          </Badge>
        )}
        {data.feedback === "down" && (
          <Badge className="border-0 bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
            <ThumbsDown className="mr-1 h-3 w-3" /> Négatif
          </Badge>
        )}
        {data.rag_trace?.out_of_scope && (
          <Badge
            variant="outline"
            className="border-orange-300 text-orange-600"
          >
            Hors-scope
          </Badge>
        )}
        <Badge variant="outline" className="font-mono">
          <DollarSign className="mr-1 h-3 w-3" />
          {fmtUsd(data.cost_usd)}
        </Badge>
        <Badge variant="outline" className="font-mono">
          <Clock className="mr-1 h-3 w-3" />
          {fmtMs(data.latency_ms)}
        </Badge>
        {data.rag_trace?.model && (
          <Badge variant="outline">{data.rag_trace.model}</Badge>
        )}
      </div>

      {/* Contexte organisation */}
      {(data.organisation_name ||
        data.user_profil_metier ||
        (data.org_idccs && data.org_idccs.length > 0)) && (
        <div className="bg-muted/30 space-y-2 rounded-md border p-3 text-xs">
          <div className="text-muted-foreground text-xs font-semibold uppercase">
            Contexte org au moment de la question
          </div>
          <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            {data.user_profil_metier && (
              <div>
                <span className="text-muted-foreground">
                  Profil utilisateur :{" "}
                </span>
                <span className="font-medium">{data.user_profil_metier}</span>
              </div>
            )}
            {data.org_forme_juridique && (
              <div>
                <span className="text-muted-foreground">Forme : </span>
                <span className="font-medium">{data.org_forme_juridique}</span>
              </div>
            )}
            {data.org_taille && (
              <div>
                <span className="text-muted-foreground">Effectif : </span>
                <span className="font-medium">{data.org_taille} salariés</span>
              </div>
            )}
            {data.org_secteur_activite && (
              <div>
                <span className="text-muted-foreground">Secteur : </span>
                <span className="font-medium">{data.org_secteur_activite}</span>
              </div>
            )}
            {data.org_convention_collective && (
              <div className="sm:col-span-2">
                <span className="text-muted-foreground">CCN saisie : </span>
                <span className="font-medium">
                  {data.org_convention_collective}
                </span>
              </div>
            )}
          </div>
          {data.org_idccs && data.org_idccs.length > 0 ? (
            <div className="pt-1">
              <div className="text-muted-foreground mb-1">
                CCN installées ({data.org_idccs.length}) :
              </div>
              <div className="flex flex-wrap gap-1.5">
                {data.org_idccs.map((c) => (
                  <Badge
                    key={c.idcc}
                    variant="outline"
                    className={
                      c.status === "ready"
                        ? "font-mono text-[11px]"
                        : "font-mono text-[11px] opacity-60"
                    }
                    title={`${c.titre ?? ""} — statut: ${c.status}${c.use_custom ? " (custom)" : ""}`}
                  >
                    IDCC {c.idcc}
                    {c.titre && (
                      <span className="ml-1 font-sans font-normal">
                        — {c.titre}
                      </span>
                    )}
                    {c.status !== "ready" && (
                      <span className="text-muted-foreground ml-1">
                        ({c.status})
                      </span>
                    )}
                  </Badge>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded border border-orange-200 bg-orange-50 px-2 py-1.5 text-orange-700 dark:border-orange-900 dark:bg-orange-950/30 dark:text-orange-300">
              <span className="font-semibold">Aucune CCN installée.</span> La
              recherche exclut désormais toutes les CCN/accords de branche pour
              éviter de remonter des sources hors-secteur. L&apos;utilisateur
              doit installer sa CCN dans son profil organisation.
            </div>
          )}
        </div>
      )}

      {/* Risk banner: identifier in query but no chunk matched */}
      {data.rag_trace?.identifier_no_match && (
        <div className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 p-3 dark:border-orange-900 dark:bg-orange-950/30">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-orange-600 dark:text-orange-400" />
          <div className="text-xs text-orange-800 dark:text-orange-200">
            <div className="mb-0.5 font-semibold">
              Risque d&apos;hallucination détecté
            </div>
            La question contient un identifiant explicite (article ou numéro de
            pourvoi) mais aucun chunk correspondant n&apos;a été trouvé dans le
            corpus indexé. La réponse ci-dessous a été générée à partir de
            chunks remontés
            <strong> par devinette sémantique du LLM d&apos;expansion</strong>,
            pas à partir de l&apos;identifiant demandé. Vérifiez que la réponse
            traite bien du sujet attendu.
          </div>
        </div>
      )}

      {/* Question */}
      <div>
        <h3 className="text-muted-foreground mb-1 text-xs font-semibold uppercase">
          Question
        </h3>
        <div className="text-sm whitespace-pre-wrap">
          {data.question || "(non retrouvée)"}
        </div>
        {data.rag_trace?.query_condensed &&
          data.rag_trace.query_condensed !== data.question && (
            <div className="text-muted-foreground mt-2 text-xs">
              <span className="font-medium">Reformulée : </span>
              <span className="italic">{data.rag_trace.query_condensed}</span>
            </div>
          )}
      </div>

      {data.rag_trace?.search_plan && (
        <SearchPlanPanel
          plan={data.rag_trace.search_plan}
          usage={data.rag_trace.search_plan_usage}
        />
      )}

      {/* Réponse */}
      {data.answer && (
        <div>
          <h3 className="text-muted-foreground mb-1 text-xs font-semibold uppercase">
            Réponse
          </h3>
          <div className="bg-muted/30 rounded-md p-4">
            <div className="prose prose-sm dark:prose-invert max-w-none text-[0.875rem] leading-6 [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-base [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_strong]:font-semibold [&_table]:my-3 [&_table]:border [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
              >
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
              Documents que l&apos;utilisateur a vus dans le panneau Sources de
              sa réponse. Cliquez sur une source pour afficher son texte
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
          <h3 className="text-muted-foreground mb-1 text-xs font-semibold uppercase">
            Commentaire utilisateur
          </h3>
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-900/20">
            {data.feedback_comment}
          </div>
        </div>
      )}

      {/* Performance */}
      {data.rag_trace &&
        Object.keys(data.rag_trace.perf_ms || {}).length > 0 && (
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
                <br />• <strong>parent_expansion</strong> : élargissement aux
                chunks frères
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
          <div className="text-muted-foreground text-xs italic">
            Trace non disponible (question antérieure à la mise en place du
            tracing).
          </div>
        </div>
      ) : (
        <>
          {data.rag_trace.variants.length > 0 && (
            <Section
              title="Reformulation pour la recherche"
              help={
                <>
                  Variantes de la question utilisées pour la recherche. La{" "}
                  <strong>1ère est la question originale</strong> (recherche
                  texte exact via BM25). Les suivantes sont générées par un
                  petit LLM pour couvrir l&apos;intention sémantique, la
                  terminologie juridique et des mots-clés.
                </>
              }
            >
              <ol className="space-y-1 text-xs">
                {data.rag_trace.variants.map((v, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-muted-foreground font-mono">
                      {i + 1}.
                    </span>
                    <span>{v}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {data.rag_trace.identifiers_detected.numero_pourvoi?.length ||
          data.rag_trace.identifiers_detected.article_nums?.length ? (
            <Section
              title="Identifiants détectés dans la query"
              help={
                <>
                  Numéros d&apos;article ou de pourvoi trouvés dans la question
                  via regex. Pour ces identifiants, on cherche directement dans
                  Qdrant via filtre payload (boost) pour garantir que les chunks
                  correspondants remontent, même si leur contenu est
                  sémantiquement éloigné de la query.
                </>
              }
            >
              <div className="flex flex-wrap gap-2">
                {data.rag_trace.identifiers_detected.numero_pourvoi?.map(
                  (p) => (
                    <Badge key={p} variant="secondary">
                      Pourvoi {p}
                    </Badge>
                  )
                )}
                {data.rag_trace.identifiers_detected.article_nums?.map((a) => (
                  <Badge key={a} variant="secondary">
                    Article {a}
                  </Badge>
                ))}
                {data.rag_trace.boost_injected > 0 && (
                  <Badge className="border-0 bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
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
                (small-to-big). Chaque ligne représente un parent group (souvent
                plusieurs chunks fusionnés en un seul contexte).
              </>
            }
          >
            <div className="space-y-2">
              {data.rag_trace.parent_groups.length === 0 ? (
                <div className="text-muted-foreground text-xs">
                  Aucune source remontée
                </div>
              ) : (
                data.rag_trace.parent_groups.map((c, i) => (
                  <ChunkRow
                    key={`${c.document_id}-${c.chunk_index}`}
                    chunk={c}
                    rank={i + 1}
                  />
                ))
              )}
            </div>
          </Section>

          <Section
            title={`Chunks après rerank (${data.rag_trace.rerank_results.length})`}
            icon={<FileSearch className="h-4 w-4" />}
            help={
              <>
                Top chunks après tri par cross-encoder Voyage rerank-2. Le
                rerank prend les ~30 candidats du pool initial et les trie selon
                la pertinence réelle (modèle plus précis mais plus coûteux que
                la recherche initiale).
              </>
            }
          >
            <div className="space-y-2">
              {data.rag_trace.rerank_results.map((c, i) => (
                <ChunkRow
                  key={`r-${c.document_id}-${c.chunk_index}-${i}`}
                  chunk={c}
                  rank={i + 1}
                />
              ))}
            </div>
          </Section>

          <Section
            title={`Pool initial avant rerank (${data.rag_trace.hybrid_results.length})`}
            help={
              <>
                Candidats remontés par la recherche hybride (dense Voyage law-2
                + sparse BM25, fusion RRF), avant le rerank. C&apos;est à cette
                étape que tu vois si le bon document a au moins été trouvé par
                le moteur de recherche.
              </>
            }
          >
            <div className="space-y-2">
              {data.rag_trace.hybrid_results.map((c, i) => (
                <ChunkRow
                  key={`h-${c.document_id}-${c.chunk_index}-${i}`}
                  chunk={c}
                  rank={i + 1}
                />
              ))}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
