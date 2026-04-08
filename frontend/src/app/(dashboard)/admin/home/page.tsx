"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  Users,
  Library,
  RefreshCw,
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  Clock,
  Database,
  Cpu,
  TrendingUp,
  Gauge,
  DollarSign,
  Activity,
  ArrowRight,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InfoTooltip } from "@/components/admin/info-tooltip";

interface Incident {
  id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string | null;
  action_label: string;
  action_href: string;
}

interface QualityHealth {
  feedback_negative_rate_7d: number;
  no_sources_rate_7d: number;
  out_of_scope_count_7d: number;
  latency_p95_ms_7d: number | null;
}

interface TimeseriesPoint {
  date: string;
  questions: number;
}

interface DashboardStats {
  total_users: number;
  active_users: number;
  total_organisations: number;
  total_documents: number;
  indexed_documents: number;
  pending_documents: number;
  error_documents: number;
  bocc_reserve: number;
  total_chunks: number;
  questions_7d: number;
  questions_today: number;
  ingestions_7d: number;
  cost_7d: number;
  questions_30d: number;
  cost_30d: number;
  last_sync_type: string | null;
  last_sync_status: string | null;
  last_sync_at: string | null;
  failed_syncs_24h: number;
  current_model: string;
  quality_health: QualityHealth;
  incidents: Incident[];
  questions_timeline_30d: TimeseriesPoint[];
}

// ----------------- Helpers -----------------

function fmtCost(v: number): string {
  if (v < 0.01 && v > 0) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function fmtMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function fmtRelativeDate(iso: string | null): string {
  if (!iso) return "jamais";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `il y a ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.floor(hours / 24);
  return `il y a ${days} j`;
}

function projectedMonthlyCost(cost30d: number): number {
  // Linear projection for the current month
  return cost30d * (30 / 30);
}

// ----------------- KPI Card -----------------

function KpiCard({
  href,
  title,
  icon,
  value,
  subValue,
  severity,
  help,
}: {
  href: string;
  title: string;
  icon: React.ReactNode;
  value: string;
  subValue?: string;
  severity: "green" | "orange" | "red" | "neutral";
  help?: React.ReactNode;
}) {
  const bgClass = {
    green: "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900 hover:bg-green-100 dark:hover:bg-green-950/50",
    orange: "bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900 hover:bg-orange-100 dark:hover:bg-orange-950/50",
    red: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900 hover:bg-red-100 dark:hover:bg-red-950/50",
    neutral: "hover:bg-muted/50",
  }[severity];

  return (
    <Link href={href}>
      <Card className={`${bgClass} cursor-pointer transition-colors h-full`}>
        <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            {icon}
            {title}
            {help && (
              <span onClick={(e) => e.preventDefault()}>
                <InfoTooltip>{help}</InfoTooltip>
              </span>
            )}
          </CardTitle>
          <ArrowRight className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold">{value}</div>
          {subValue && (
            <div className="text-xs text-muted-foreground mt-1">{subValue}</div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

// ----------------- Incident banner -----------------

const DISMISS_KEY = "aoria.dashboard.dismissed_incidents";

/** Compute a stable fingerprint for an incident so the dismissal
 *  re-appears automatically when the situation changes (e.g. error
 *  count goes from 3 to 5). */
function incidentFingerprint(inc: Incident): string {
  return `${inc.id}|${inc.title}|${inc.detail ?? ""}`;
}

function readDismissed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function writeDismissed(s: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DISMISS_KEY, JSON.stringify(Array.from(s)));
  } catch {
    // localStorage full / blocked — silent fallback, dismissal lasts only this session
  }
}

function IncidentsBanner({ incidents }: { incidents: Incident[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Hydrate from localStorage on mount
  useEffect(() => {
    setDismissed(readDismissed());
  }, []);

  // Garbage-collect dismissals that no longer match any current incident
  // so we don't accumulate stale entries forever.
  useEffect(() => {
    if (dismissed.size === 0) return;
    const live = new Set(incidents.map(incidentFingerprint));
    const cleaned = new Set([...dismissed].filter((fp) => live.has(fp)));
    if (cleaned.size !== dismissed.size) {
      setDismissed(cleaned);
      writeDismissed(cleaned);
    }
  }, [incidents, dismissed]);

  const dismiss = (inc: Incident) => {
    const next = new Set(dismissed);
    next.add(incidentFingerprint(inc));
    setDismissed(next);
    writeDismissed(next);
  };

  const visible = incidents.filter((inc) => !dismissed.has(incidentFingerprint(inc)));

  if (visible.length === 0) {
    return (
      <Card className="bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-900">
        <CardContent className="p-4 flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-green-600 dark:text-green-400" />
          <div className="text-sm font-medium text-green-700 dark:text-green-300">
            Aucun incident en cours.
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold flex items-center gap-2">
          <AlertOctagon className="h-4 w-4" />
          Incidents en cours ({visible.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {visible.map((inc) => {
          const colors =
            inc.severity === "critical"
              ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900 text-red-700 dark:text-red-300"
              : inc.severity === "warning"
              ? "bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900 text-orange-700 dark:text-orange-300"
              : "bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300";
          const Icon = inc.severity === "critical" ? AlertOctagon : AlertTriangle;
          return (
            <div
              key={inc.id}
              className={`border rounded-md p-3 flex items-start gap-3 ${colors}`}
            >
              <Icon className="h-4 w-4 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm">{inc.title}</div>
                {inc.detail && (
                  <div className="text-xs opacity-80 mt-0.5">{inc.detail}</div>
                )}
              </div>
              <Link href={inc.action_href}>
                <Button size="sm" variant="outline" className="bg-background shrink-0">
                  {inc.action_label}
                </Button>
              </Link>
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 shrink-0 hover:bg-background/60"
                title="Masquer (réapparaît si la situation change)"
                onClick={() => dismiss(inc)}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ----------------- Timeline chart (SVG) -----------------

function TimelineChart({ data }: { data: TimeseriesPoint[] }) {
  if (data.length === 0) {
    return (
      <div className="text-xs text-muted-foreground py-12 text-center">
        Pas de données sur les 30 derniers jours.
      </div>
    );
  }
  const max = Math.max(...data.map((d) => d.questions), 1);
  const width = 800;
  const height = 160;
  const padding = { top: 10, right: 10, bottom: 25, left: 30 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const barWidth = (chartW / data.length) * 0.7;
  const step = chartW / data.length;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-40">
      {/* Y-axis lines */}
      {[0, 0.25, 0.5, 0.75, 1].map((p) => {
        const y = padding.top + chartH - chartH * p;
        return (
          <g key={p}>
            <line
              x1={padding.left}
              x2={width - padding.right}
              y1={y}
              y2={y}
              stroke="currentColor"
              strokeOpacity="0.1"
              strokeWidth="1"
            />
            <text
              x={padding.left - 4}
              y={y + 3}
              textAnchor="end"
              fontSize="9"
              fill="currentColor"
              fillOpacity="0.5"
            >
              {Math.round(max * p)}
            </text>
          </g>
        );
      })}
      {/* Bars */}
      {data.map((d, i) => {
        const h = (d.questions / max) * chartH;
        const x = padding.left + i * step + (step - barWidth) / 2;
        const y = padding.top + chartH - h;
        return (
          <g key={d.date}>
            <rect
              x={x}
              y={y}
              width={barWidth}
              height={h}
              className="fill-primary"
              opacity={0.85}
            >
              <title>{`${d.date}: ${d.questions} question(s)`}</title>
            </rect>
          </g>
        );
      })}
      {/* X-axis labels (first, middle, last) */}
      {[0, Math.floor(data.length / 2), data.length - 1].map((i) => {
        if (i < 0 || i >= data.length) return null;
        const x = padding.left + i * step + step / 2;
        const date = new Date(data[i].date);
        const label = date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
        return (
          <text
            key={i}
            x={x}
            y={height - 8}
            textAnchor="middle"
            fontSize="10"
            fill="currentColor"
            fillOpacity="0.6"
          >
            {label}
          </text>
        );
      })}
    </svg>
  );
}

// ----------------- Page -----------------

export default function AdminHomePage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<DashboardStats>("/admin/dashboard/", { token });
      setStats(data);
    } catch {
      toast.error("Erreur lors du chargement du tableau de bord");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Vue d&apos;ensemble</h1>
        <Skeleton className="h-20 w-full" />
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-32" />)}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!stats) return null;

  // Severity logic for the 4 main cards
  const ragSeverity: "green" | "orange" | "red" =
    stats.quality_health.feedback_negative_rate_7d > 0.15
      ? "red"
      : stats.quality_health.feedback_negative_rate_7d > 0.05 ||
        stats.quality_health.no_sources_rate_7d > 0.05
      ? "orange"
      : "green";

  const corpusSeverity: "green" | "orange" | "red" =
    stats.error_documents > 0
      ? "red"
      : stats.pending_documents > 10
      ? "orange"
      : "green";

  const projection = projectedMonthlyCost(stats.cost_30d);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Vue d&apos;ensemble</h1>
          <p className="text-sm text-muted-foreground">
            État de santé d&apos;AORIA RH en temps réel.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchStats}>
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>

      {/* Incidents banner */}
      <IncidentsBanner incidents={stats.incidents} />

      {/* 4 main KPI cards (clickable) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          href="/admin/quality"
          title="Santé RAG"
          icon={<Gauge className="h-4 w-4" />}
          value={fmtPct(stats.quality_health.feedback_negative_rate_7d)}
          subValue={`${fmtPct(stats.quality_health.no_sources_rate_7d)} sans source · p95 ${fmtMs(stats.quality_health.latency_p95_ms_7d)}`}
          severity={ragSeverity}
          help={
            <>
              Indicateur de santé du moteur RAG sur les 7 derniers jours.
              Valeur affichée = taux de feedback négatif.
              Sous-info = taux de questions sans source + latence p95.
              Cliquez pour ouvrir la page Qualité.
            </>
          }
        />
        <KpiCard
          href="/admin/costs"
          title="Coût (30j)"
          icon={<DollarSign className="h-4 w-4" />}
          value={fmtCost(stats.cost_30d)}
          subValue={`projection mensuelle ~ ${fmtCost(projection)}`}
          severity="neutral"
          help={
            <>
              Coût total des appels API (OpenAI + Voyage AI) sur 30 jours,
              uniquement pour les questions utilisateurs (les ingestions et
              le bac à sable admin sont exclus).
            </>
          }
        />
        <KpiCard
          href="/admin/corpus"
          title="Corpus juridique"
          icon={<Library className="h-4 w-4" />}
          value={`${stats.indexed_documents.toLocaleString("fr-FR")}`}
          subValue={`${stats.error_documents} erreur · ${stats.pending_documents} en attente`}
          severity={corpusSeverity}
          help={
            <>
              Nombre de documents communs indexés et interrogeables par le
              RAG (codes, conventions collectives, jurisprudence). Carte
              orange si docs en attente, rouge si docs en erreur.
            </>
          }
        />
        <KpiCard
          href="/admin/quality"
          title="Activité (7j)"
          icon={<Activity className="h-4 w-4" />}
          value={stats.questions_7d.toLocaleString("fr-FR")}
          subValue={`${stats.questions_today} aujourd'hui · ${stats.active_users}/${stats.total_users} utilisateurs actifs`}
          severity="neutral"
          help={
            <>
              Nombre de questions posées dans le chat sur 7 jours, hors
              tests admin. <strong>Utilisateurs actifs</strong> = comptes
              ayant posé au moins 1 question récemment.
            </>
          }
        />
      </div>

      {/* Timeline chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Questions par jour (30 jours)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <TimelineChart data={stats.questions_timeline_30d} />
        </CardContent>
      </Card>

      {/* Secondary info row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase font-medium text-muted-foreground flex items-center gap-2">
              <Clock className="h-3 w-3" />
              Dernière sync
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium">
              {stats.last_sync_type ?? "—"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {fmtRelativeDate(stats.last_sync_at)}
              {stats.last_sync_status && (
                <Badge
                  variant="outline"
                  className={`ml-2 text-[10px] h-4 ${
                    ["ok", "success", "completed"].includes(stats.last_sync_status.toLowerCase())
                      ? "border-green-300 text-green-700 dark:text-green-400"
                      : "border-red-300 text-red-700 dark:text-red-400"
                  }`}
                >
                  {stats.last_sync_status}
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase font-medium text-muted-foreground flex items-center gap-2">
              <Cpu className="h-3 w-3" />
              Modèle LLM
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-mono font-medium">{stats.current_model}</div>
            <Link href="/admin/costs" className="text-xs text-muted-foreground hover:underline mt-1 block">
              Changer →
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase font-medium text-muted-foreground flex items-center gap-2">
              <Database className="h-3 w-3" />
              Index Qdrant
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium">
              {stats.total_chunks.toLocaleString("fr-FR")} chunks
            </div>
            <Link href="/admin/qdrant" className="text-xs text-muted-foreground hover:underline mt-1 block">
              Inspecter →
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase font-medium text-muted-foreground flex items-center gap-2">
              <Users className="h-3 w-3" />
              Comptes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm font-medium">
              {stats.total_organisations} orgs · {stats.total_users} users
            </div>
            <Link href="/admin/users" className="text-xs text-muted-foreground hover:underline mt-1 block">
              Gérer →
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
