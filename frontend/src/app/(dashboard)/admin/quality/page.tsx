"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
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
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  if (usd < 0.01) return `${(usd * 1000).toFixed(2)} m$`;
  return `$${usd.toFixed(4)}`;
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

function TrendArrow({ delta, invertColor = false }: { delta: number | null; invertColor?: boolean }) {
  if (delta === null) {
    return <Minus className="h-3 w-3 text-muted-foreground" />;
  }
  const isUp = delta > 0;
  // For some metrics (like negative rate or latency), going up is bad
  const isBad = invertColor ? isUp : !isUp;
  const colorClass = isBad ? "text-red-600 dark:text-red-400" : "text-green-600 dark:text-green-400";
  return (
    <span className={`flex items-center gap-1 text-xs ${colorClass}`}>
      {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
      {Math.abs(delta).toFixed(1)}%
    </span>
  );
}

function FeedbackBadge({ feedback }: { feedback: string | null }) {
  if (feedback === "up") {
    return (
      <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-100 border-0">
        <ThumbsUp className="h-3 w-3 mr-1" /> 👍
      </Badge>
    );
  }
  if (feedback === "down") {
    return (
      <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-100 border-0">
        <ThumbsDown className="h-3 w-3 mr-1" /> 👎
      </Badge>
    );
  }
  return <span className="text-xs text-muted-foreground">—</span>;
}

// ----------------- Page -----------------

export default function QualityPage() {
  const { data: session } = useSession();
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [kpisLoading, setKpisLoading] = useState(true);
  const [period, setPeriod] = useState<number>(7);

  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const PAGE_SIZE = 50;

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [feedbackFilter, setFeedbackFilter] = useState<string>("any");

  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("conversations");
  const [sandboxReplayMessageId, setSandboxReplayMessageId] = useState<string | undefined>(undefined);

  const fetchKpis = useCallback(async () => {
    if (!session?.access_token) return;
    setKpisLoading(true);
    try {
      const data = await apiFetch<Kpis>(
        `/admin/quality/metrics?days=${period}`,
        { token: session.access_token },
      );
      setKpis(data);
    } catch (err) {
      console.error("Failed to load KPIs", err);
      toast.error("Erreur lors du chargement des indicateurs");
    } finally {
      setKpisLoading(false);
    }
  }, [session?.access_token, period]);

  const fetchConversations = useCallback(async () => {
    if (!session?.access_token) return;
    setConvLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(PAGE_SIZE));
      if (search.trim()) params.set("q", search.trim());
      if (feedbackFilter !== "any") params.set("feedback", feedbackFilter);
      const data = await apiFetch<ConversationListResponse>(
        `/admin/quality/conversations?${params.toString()}`,
        { token: session.access_token },
      );
      setConversations(data.items);
      setTotal(data.total);
    } catch (err) {
      console.error("Failed to load conversations", err);
      toast.error("Erreur lors du chargement des conversations");
    } finally {
      setConvLoading(false);
    }
  }, [session?.access_token, page, search, feedbackFilter]);

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
    [total],
  );

  return (
    <div className="space-y-6">
      {/* ----------------- Header ----------------- */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Qualité & conversations</h1>
          <p className="text-sm text-muted-foreground">
            Surveille la santé du RAG et inspecte chaque question posée.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(period)} onValueChange={(v) => setPeriod(Number(v))}>
            <SelectTrigger className="w-[140px]">
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
            onClick={() => {
              fetchKpis();
              fetchConversations();
            }}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* ----------------- KPIs ----------------- */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <KpiCard
          title="Feedback négatif"
          icon={<ThumbsDown className="h-4 w-4" />}
          loading={kpisLoading}
          value={kpis ? fmtPct(kpis.feedback_negative_rate) : "—"}
          subValue={kpis ? `${kpis.feedback_negative} / ${kpis.total_questions} questions` : ""}
          trend={kpis?.trends.negative_rate.delta_pct ?? null}
          trendInverted
          severity={
            kpis ? (kpis.feedback_negative_rate > 0.15 ? "red" : kpis.feedback_negative_rate > 0.05 ? "orange" : "green") : "neutral"
          }
          help={
            <>
              Pourcentage de questions sur lesquelles l&apos;utilisateur a cliqué 👎.
              Au-delà de 5% : à surveiller. Au-delà de 15% : urgence.
              La flèche compare à la période précédente.
            </>
          }
        />
        <KpiCard
          title="Questions sans réponse trouvée"
          icon={<AlertTriangle className="h-4 w-4" />}
          loading={kpisLoading}
          value={
            kpis
              ? `${kpis.no_sources_count} / ${kpis.total_questions}`
              : "—"
          }
          subValue={
            kpis
              ? kpis.no_sources_count === 0
                ? "Tout a trouvé une réponse appuyée sur un document"
                : "Aucun document du corpus ne correspondait"
              : ""
          }
          severity={kpis ? (kpis.no_sources_rate > 0.05 ? "orange" : "green") : "neutral"}
          help={
            <>
              Questions RH où le moteur de recherche n&apos;a trouvé{" "}
              <strong>aucun document</strong> du corpus pour appuyer sa
              réponse. Plus ce nombre est élevé, plus il manque
              probablement de documents importants à ajouter.
              <br />
              <br />
              Les questions hors sujet RH (météo, etc.) ne sont pas
              comptées ici — elles ont leur propre indicateur «&nbsp;Hors
              périmètre&nbsp;».
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
              Temps que met le système pour répondre à une question, vu
              côté utilisateur.
              <br />
              <br />
              La grande valeur est le temps <strong>habituel</strong>{" "}
              (la moitié des questions sont plus rapides, l&apos;autre
              moitié plus lentes). Le sous-titre montre le{" "}
              <strong>cas le plus lent</strong> : temps que met la
              question parmi les 5% les plus longues.
              <br />
              <br />
              Cible normale : moins de 10 secondes pour la majorité,
              moins de 20 secondes pour les cas les plus lents.
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
              Coût moyen d&apos;une question (embeddings + LLM + rerank).
              <strong> m$</strong> = millième de dollar (1 m$ = 0.001$).
              Exclut le bac à sable.
            </>
          }
        />
      </div>

      {/* ----------------- Tabs ----------------- */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="conversations">Conversations</TabsTrigger>
          <TabsTrigger value="sandbox">Bac à sable</TabsTrigger>
        </TabsList>

        <TabsContent value="conversations">
      {/* ----------------- Filters ----------------- */}
      <div className="flex flex-col md:flex-row gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher dans le contenu des questions et réponses..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select value={feedbackFilter} onValueChange={(v) => { setFeedbackFilter(v); setPage(1); }}>
          <SelectTrigger className="w-[180px]">
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
            Conversations ({total.toLocaleString("fr-FR")})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {convLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : conversations.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground text-sm">
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
                  <TableHead className="w-[80px] text-center">Feedback</TableHead>
                  <TableHead className="w-[80px] text-right">Latence</TableHead>
                  <TableHead className="w-[90px] text-right">Coût</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {conversations.map((c) => (
                  <TableRow
                    key={c.message_id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedMessageId(c.message_id)}
                  >
                    <TableCell className="text-xs text-muted-foreground">
                      {fmtDate(c.created_at)}
                    </TableCell>
                    <TableCell className="text-xs truncate max-w-[180px]">
                      {c.user_email ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs truncate max-w-[160px]">
                      {c.organisation_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      <div className="line-clamp-2">{c.question || "(question non retrouvée)"}</div>
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
        <div className="flex items-center justify-between mt-4">
          <span className="text-xs text-muted-foreground">
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
    red:
      "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900",
    neutral: "",
  }[severity];

  return (
    <Card className={bgClass}>
      <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
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
            <div className="flex items-center gap-2 mt-1">
              {subValue && <span className="text-xs text-muted-foreground">{subValue}</span>}
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
