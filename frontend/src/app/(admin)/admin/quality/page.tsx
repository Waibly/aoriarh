"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ThumbsUp,
  ThumbsDown,
  AlertTriangle,
  Search,
  Clock,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Minus,
  RefreshCw,
} from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { AdminLoadError } from "@/components/admin/page-header";
import { InfoTooltip } from "@/components/admin/info-tooltip";
import { ConversationInspector } from "./ConversationInspector";
import { SandboxRunner } from "./SandboxRunner";

// ----------------- Types -----------------

interface Trend {
  current: number;
  previous: number;
  delta_pct: number | null;
}

interface Kpis {
  period_days: number;
  total_questions: number;
  feedback_positive: number;
  feedback_negative: number;
  feedback_none: number;
  feedback_negative_rate: number;
  out_of_scope_count: number;
  out_of_scope_rate: number;
  no_sources_count: number;
  no_sources_rate: number;
  error_count: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  cost_total_usd: number;
  cost_avg_per_question_usd: number | null;
  trends: {
    negative_rate: Trend;
    latency_p95_ms: Trend;
    cost_avg: Trend;
  };
}

interface ConversationItem {
  message_id: string;
  conversation_id: string;
  created_at: string;
  user_email: string | null;
  organisation_name: string | null;
  question: string;
  answer_preview: string;
  feedback: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  has_trace: boolean;
  is_demo: boolean;
}

interface ConversationListResponse {
  items: ConversationItem[];
  page: number;
  page_size: number;
  total: number;
}

// ----------------- Helpers -----------------

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmtMs(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function fmtUsd(usd: number | null): string {
  if (usd === null || usd === undefined) return "—";
  if (Math.abs(usd) < 0.01) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function TrendArrow({
  delta,
  invertColor = false,
}: {
  delta: number | null;
  invertColor?: boolean;
}) {
  if (delta === null) {
    return (
      <span className="text-muted-foreground flex items-center gap-1 text-xs">
        <Minus className="h-3 w-3" />
        vs période préc.
      </span>
    );
  }
  const isUp = delta > 0;
  // For some metrics (like negative rate or latency), going up is bad
  const isBad = invertColor ? isUp : !isUp;
  const colorClass = isBad
    ? "text-red-600 dark:text-red-400"
    : "text-green-600 dark:text-green-400";
  return (
    <span className={`flex items-center gap-1 text-xs ${colorClass}`}>
      {isUp ? (
        <TrendingUp className="h-3 w-3" />
      ) : (
        <TrendingDown className="h-3 w-3" />
      )}
      {Math.abs(delta).toFixed(1).replace(".", ",")}% vs période préc.
    </span>
  );
}

function FeedbackBadge({ feedback }: { feedback: string | null }) {
  if (feedback === "up") {
    return (
      <Badge className="border-0 bg-green-100 text-green-700 hover:bg-green-100 dark:bg-green-900/30 dark:text-green-400">
        <ThumbsUp className="mr-1 h-3 w-3" /> 👍
      </Badge>
    );
  }
  if (feedback === "down") {
    return (
      <Badge className="border-0 bg-red-100 text-red-700 hover:bg-red-100 dark:bg-red-900/30 dark:text-red-400">
        <ThumbsDown className="mr-1 h-3 w-3" /> 👎
      </Badge>
    );
  }
  return <span className="text-muted-foreground text-xs">—</span>;
}

// ----------------- Page -----------------

function QualityPageContent() {
  const { data: session } = useSession();
  const searchParams = useSearchParams();
  const accountId = searchParams.get("account_id");
  const accountName = searchParams.get("account_name");
  const requestedDays = Number(searchParams.get("days"));
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [kpisLoading, setKpisLoading] = useState(true);
  const [kpisError, setKpisError] = useState(false);
  const [period, setPeriod] = useState<number>(
    [1, 7, 30, 90].includes(requestedDays) ? requestedDays : 7
  );

  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [convError, setConvError] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const PAGE_SIZE = 50;

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [feedbackFilter, setFeedbackFilter] = useState<string>(
    ["up", "down", "none"].includes(searchParams.get("feedback") || "")
      ? searchParams.get("feedback")!
      : "any"
  );

  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(
    null
  );
  const [activeTab, setActiveTab] = useState("conversations");
  const [sandboxReplayMessageId, setSandboxReplayMessageId] = useState<
    string | undefined
  >(undefined);

  const fetchKpis = useCallback(async () => {
    if (!session?.access_token) return;
    setKpisLoading(true);
    setKpisError(false);
    try {
      const params = new URLSearchParams({ days: String(period) });
      if (accountId) params.set("account_id", accountId);
      const data = await apiFetch<Kpis>(
        `/admin/quality/metrics?${params.toString()}`,
        { token: session.access_token }
      );
      setKpis(data);
    } catch (err) {
      setKpisError(true);
      console.error("Failed to load KPIs", err);
      toast.error("Erreur lors du chargement des indicateurs");
    } finally {
      setKpisLoading(false);
    }
  }, [session?.access_token, period, accountId]);

  const fetchConversations = useCallback(async () => {
    if (!session?.access_token) return;
    setConvLoading(true);
    setConvError(false);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(PAGE_SIZE));
      params.set("days", String(period));
      if (accountId) params.set("account_id", accountId);
      if (search.trim()) params.set("q", search.trim());
      if (feedbackFilter !== "any") params.set("feedback", feedbackFilter);
      const data = await apiFetch<ConversationListResponse>(
        `/admin/quality/conversations?${params.toString()}`,
        { token: session.access_token }
      );
      setConversations(data.items);
      setTotal(data.total);
    } catch (err) {
      setConvError(true);
      console.error("Failed to load conversations", err);
      toast.error("Erreur lors du chargement des conversations");
    } finally {
      setConvLoading(false);
    }
  }, [session?.access_token, page, search, feedbackFilter, period, accountId]);

  useEffect(() => {
    fetchKpis();
  }, [fetchKpis]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  // Debounce search input → search
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total]
  );

  return (
    <div className="space-y-6">
      {/* ----------------- Header ----------------- */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">Conversations & retours</h1>
          <p className="text-muted-foreground text-sm">
            {accountId
              ? `Questions et réponses de ${accountName || "ce client"}.`
              : "Consultez les échanges, les retours utilisateurs et les sources associées."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={String(period)}
            onValueChange={(v) => {
              setPeriod(Number(v));
              setPage(1);
            }}
          >
            <SelectTrigger
              aria-label="Période des conversations"
              className="w-full sm:w-[140px]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">24 heures</SelectItem>
              <SelectItem value="7">7 jours</SelectItem>
              <SelectItem value="30">30 jours</SelectItem>
              <SelectItem value="90">90 jours</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            aria-label="Actualiser les conversations et les indicateurs"
            onClick={() => {
              fetchKpis();
              fetchConversations();
            }}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {kpisError && (
        <AdminLoadError
          message="Impossible d’actualiser les indicateurs pour cette période."
          onRetry={fetchKpis}
        />
      )}
      {/* ----------------- KPIs ----------------- */}
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Retours négatifs"
          icon={<ThumbsDown className="h-4 w-4" />}
          loading={kpisLoading}
          value={kpis ? fmtPct(kpis.feedback_negative_rate) : "—"}
          subValue={
            kpis
              ? `${kpis.feedback_negative} / ${kpis.total_questions} questions`
              : ""
          }
          trend={kpis?.trends.negative_rate.delta_pct ?? null}
          trendInverted
          severity={
            kpis
              ? kpis.feedback_negative_rate > 0.15
                ? "red"
                : kpis.feedback_negative_rate > 0.05
                  ? "orange"
                  : "green"
              : "neutral"
          }
          help={
            <>
              Pourcentage de questions sur lesquelles l&apos;utilisateur a
              cliqué 👎. Au-delà de 5% : à surveiller. Au-delà de 15% : urgence.
              La flèche compare à la période précédente.
            </>
          }
        />
        <KpiCard
          title="Questions sans source retrouvée"
          icon={<AlertTriangle className="h-4 w-4" />}
          loading={kpisLoading}
          value={
            kpis ? `${kpis.no_sources_count} / ${kpis.total_questions}` : "—"
          }
          subValue={
            kpis
              ? kpis.no_sources_count === 0
                ? "Aucune absence de source enregistrée"
                : "Aucune source retrouvée par la recherche"
              : ""
          }
          severity={
            kpis
              ? kpis.no_sources_rate > 0.05
                ? "orange"
                : "green"
              : "neutral"
          }
          help={
            <>
              Questions RH où le moteur de recherche n&apos;a trouvé{" "}
              <strong>aucun document</strong> du corpus pour appuyer sa réponse.
              Plus ce nombre est élevé, plus il manque probablement de documents
              importants à ajouter.
              <br />
              <br />
              Les questions hors sujet RH (météo, etc.) ne sont pas comptées ici
              — elles ont leur propre indicateur «&nbsp;Hors périmètre&nbsp;».
            </>
          }
        />
        <KpiCard
          title="Temps de réponse"
          icon={<Clock className="h-4 w-4" />}
          loading={kpisLoading}
          value={kpis ? fmtMs(kpis.latency_p50_ms) : "—"}
          subValue={
            kpis
              ? `Cas le plus lent (5% des questions) : ${fmtMs(kpis.latency_p95_ms)}`
              : ""
          }
          trend={kpis?.trends.latency_p95_ms.delta_pct ?? null}
          trendInverted
          severity={
            kpis && kpis.latency_p95_ms !== null
              ? kpis.latency_p95_ms > 20000
                ? "red"
                : kpis.latency_p95_ms > 12000
                  ? "orange"
                  : "green"
              : "neutral"
          }
          help={
            <>
              Temps que met le système pour répondre à une question, vu côté
              utilisateur.
              <br />
              <br />
              La grande valeur est le temps <strong>habituel</strong> (la moitié
              des questions sont plus rapides, l&apos;autre moitié plus lentes).
              Le sous-titre montre le <strong>cas le plus lent</strong> : temps
              que met la question parmi les 5% les plus longues.
              <br />
              <br />
              Cible normale : moins de 10 secondes pour la majorité, moins de 20
              secondes pour les cas les plus lents.
            </>
          }
        />
        <KpiCard
          title="Coût moyen / question"
          icon={<DollarSign className="h-4 w-4" />}
          loading={kpisLoading}
          value={kpis ? fmtUsd(kpis.cost_avg_per_question_usd) : "—"}
          subValue={kpis ? `${fmtUsd(kpis.cost_total_usd)} total` : ""}
          trend={kpis?.trends.cost_avg.delta_pct ?? null}
          trendInverted
          severity="neutral"
          help={
            <>
              Coût moyen d&apos;une question (embeddings + LLM + rerank). Pour
              les montants inférieurs à 1 cent, affichage en dollars avec 4
              décimales (ex: $0.0096 ≈ 1 centime). Exclut le bac à sable.
            </>
          }
        />
      </div>

      {/* ----------------- Tabs ----------------- */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            <TabsTrigger value="conversations">Conversations</TabsTrigger>
            {activeTab === "sandbox" && (
              <TabsTrigger value="sandbox">
                Test manuel de la question
              </TabsTrigger>
            )}
          </TabsList>
          <Button variant="outline" size="sm" asChild>
            <Link href="/admin/tools">Outils de test</Link>
          </Button>
        </div>

        <TabsContent value="conversations">
          {/* ----------------- Filters ----------------- */}
          {accountId && (
            <div className="bg-muted/30 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
              <div className="text-sm">
                <span className="text-muted-foreground">Client filtré : </span>
                {session?.user?.staff_role === "tech" ? (
                  <span className="font-medium">
                    {accountName || accountId}
                  </span>
                ) : (
                  <Link
                    href={`/admin/clients/${accountId}`}
                    className="text-primary font-medium hover:underline"
                  >
                    {accountName || accountId}
                  </Link>
                )}
                <span className="text-muted-foreground">
                  {" "}
                  · {period} derniers jours
                </span>
              </div>
              <Button variant="outline" size="sm" asChild>
                <Link href="/admin/quality">Voir tous les clients</Link>
              </Button>
            </div>
          )}
          <div className="mb-4 flex flex-col gap-3 md:flex-row">
            <div className="relative flex-1">
              <Search className="text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
              <Input
                aria-label="Rechercher dans les questions et réponses"
                placeholder="Rechercher une question ou une réponse…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select
              value={feedbackFilter}
              onValueChange={(v) => {
                setFeedbackFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger
                aria-label="Filtrer les retours utilisateurs"
                className="w-full sm:w-[180px]"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Tous les feedbacks</SelectItem>
                <SelectItem value="up">👍 Positifs</SelectItem>
                <SelectItem value="down">👎 Négatifs</SelectItem>
                <SelectItem value="none">Sans feedback</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* ----------------- Conversations table ----------------- */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base font-semibold">
                Questions et réponses ({total.toLocaleString("fr-FR")})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {convError ? (
                <AdminLoadError
                  message="Impossible de charger les conversations."
                  onRetry={fetchConversations}
                />
              ) : convLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : conversations.length === 0 ? (
                <div className="text-muted-foreground py-12 text-center text-sm">
                  Aucune conversation trouvée pour ces filtres.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[110px]">Date</TableHead>
                      <TableHead className="w-[180px]">Utilisateur</TableHead>
                      <TableHead className="w-[160px]">Organisation</TableHead>
                      <TableHead>Question</TableHead>
                      <TableHead className="w-[80px] text-center">
                        Feedback
                      </TableHead>
                      <TableHead className="w-[80px] text-right">
                        Latence
                      </TableHead>
                      <TableHead className="w-[90px] text-right">
                        Coût
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {conversations.map((c) => (
                      <TableRow
                        key={c.message_id}
                        className="hover:bg-muted/50 cursor-pointer"
                        onClick={() => setSelectedMessageId(c.message_id)}
                      >
                        <TableCell className="text-muted-foreground text-xs">
                          {fmtDate(c.created_at)}
                        </TableCell>
                        <TableCell className="max-w-[180px] truncate text-xs">
                          {c.user_email ?? "—"}
                        </TableCell>
                        <TableCell className="max-w-[160px] truncate text-xs">
                          {c.organisation_name ?? "—"}
                        </TableCell>
                        <TableCell className="text-sm">
                          <button
                            className="hover:text-primary focus-visible:outline-primary w-full text-left focus-visible:outline-2"
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedMessageId(c.message_id);
                            }}
                            aria-label={`Consulter la question du ${fmtDate(c.created_at)}`}
                          >
                            <div className="whitespace-pre-wrap">
                              {c.is_demo && (
                                <Badge className="bg-primary/10 text-primary hover:bg-primary/10 mr-1.5 border-0 align-middle">
                                  Démo
                                </Badge>
                              )}
                              {c.question || "(question non retrouvée)"}
                            </div>
                          </button>
                        </TableCell>
                        <TableCell className="text-center">
                          <FeedbackBadge feedback={c.feedback} />
                        </TableCell>
                        <TableCell className="text-right text-xs">
                          {fmtMs(c.latency_ms)}
                        </TableCell>
                        <TableCell className="text-right text-xs">
                          {fmtUsd(c.cost_usd)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-muted-foreground text-xs">
                Page {page} / {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  Précédent
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  Suivant
                </Button>
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="sandbox">
          <SandboxRunner
            replayMessageId={sandboxReplayMessageId}
            onConsumed={() => setSandboxReplayMessageId(undefined)}
          />
        </TabsContent>
      </Tabs>

      {/* ----------------- Drawer ----------------- */}
      <ConversationInspector
        messageId={selectedMessageId}
        open={selectedMessageId !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedMessageId(null);
        }}
        onReplayRequest={(mid) => {
          setSandboxReplayMessageId(mid);
          setActiveTab("sandbox");
        }}
      />
    </div>
  );
}

export default function QualityPage() {
  return (
    <Suspense fallback={null}>
      <QualityPageContent />
    </Suspense>
  );
}

// ----------------- KpiCard component -----------------

function KpiCard({
  title,
  icon,
  loading,
  value,
  subValue,
  trend,
  trendInverted,
  severity,
  help,
}: {
  title: string;
  icon: React.ReactNode;
  loading: boolean;
  value: string;
  subValue?: string;
  trend?: number | null;
  trendInverted?: boolean;
  severity: "green" | "orange" | "red" | "neutral";
  help?: React.ReactNode;
}) {
  const bgClass = {
    green:
      "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900",
    orange:
      "bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900",
    red: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900",
    neutral: "",
  }[severity];

  return (
    <Card className={bgClass}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
          {icon}
          {title}
          {help && <InfoTooltip>{help}</InfoTooltip>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {loading ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <>
            <div className="text-2xl font-bold">{value}</div>
            <div className="mt-1 flex items-center gap-2">
              {subValue && (
                <span className="text-muted-foreground text-xs">
                  {subValue}
                </span>
              )}
              {trend !== undefined && (
                <TrendArrow delta={trend ?? null} invertColor={trendInverted} />
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
