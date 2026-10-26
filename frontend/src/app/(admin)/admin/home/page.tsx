"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  Users,
  Library,
  RefreshCw,
  Clock,
  Database,
  Cpu,
  TrendingUp,
  Gauge,
  DollarSign,
  Activity,
  ArrowRight,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import {
  IncidentsBanner,
  type Incident,
} from "@/components/admin/incidents-banner";
import { ServiceNav } from "@/components/admin/section-nav";
import { InfoTooltip } from "@/components/admin/info-tooltip";

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
    green:
      "bg-muted/40 border-border hover:bg-green-100 dark:hover:bg-green-950/50",
    orange:
      "bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900 hover:bg-orange-100 dark:hover:bg-orange-950/50",
    red: "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900 hover:bg-red-100 dark:hover:bg-red-950/50",
    neutral: "hover:bg-muted/50",
  }[severity];

  return (
    <Link href={href}>
      <Card className={`${bgClass} h-full cursor-pointer transition-colors`}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
            {icon}
            {title}
            {help && (
              <span onClick={(e) => e.preventDefault()}>
                <InfoTooltip>{help}</InfoTooltip>
              </span>
            )}
          </CardTitle>
          <ArrowRight className="text-muted-foreground h-4 w-4" />
        </CardHeader>
        <CardContent>
          <div className="text-3xl font-bold">{value}</div>
          {subValue && (
            <div className="text-muted-foreground mt-1 text-xs">{subValue}</div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

// ----------------- Timeline chart (SVG) -----------------

function TimelineChart({ data }: { data: TimeseriesPoint[] }) {
  if (data.length === 0) {
    return (
      <div className="text-muted-foreground py-12 text-center text-xs">
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
    <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full">
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
        const label = date.toLocaleDateString("fr-FR", {
          day: "2-digit",
          month: "short",
        });
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
  const [error, setError] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const fetchStats = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<DashboardStats>("/admin/dashboard/", {
        token,
      });
      setStats(data);
      setError(false);
      setUpdatedAt(new Date());
    } catch {
      setError(true);
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
        <h1 className="text-2xl font-bold tracking-tight">État du service</h1>
        <Skeleton className="h-20 w-full" />
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!stats) return <AdminLoadError onRetry={fetchStats} />;

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

  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Exploitation"
        title="État du service"
        description="Repérez les alertes et accédez aux conversations ou documents concernés."
        actions={
          <Button variant="outline" size="sm" onClick={fetchStats}>
            <RefreshCw className="size-4" />
            Actualiser
          </Button>
        }
      />
      <ServiceNav />
      {error && (
        <AdminLoadError
          message="L’actualisation a échoué. Les données affichées peuvent être anciennes."
          onRetry={fetchStats}
        />
      )}
      <p className="text-muted-foreground text-xs">
        Actualisation toutes les 30 secondes
        {updatedAt &&
          ` · Dernière mise à jour à ${updatedAt.toLocaleTimeString("fr-FR")}`}
      </p>
      {/* Incidents banner */}
      <IncidentsBanner incidents={stats.incidents} />

      {/* 4 main KPI cards (clickable) */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          href="/admin/quality"
          title="Retours négatifs (7 j)"
          icon={<Gauge className="h-4 w-4" />}
          value={fmtPct(stats.quality_health.feedback_negative_rate_7d)}
          subValue={`${fmtPct(stats.quality_health.no_sources_rate_7d)} sans réponse trouvée · cas le plus lent ${fmtMs(stats.quality_health.latency_p95_ms_7d)}`}
          severity={ragSeverity}
          help={
            <>
              Indicateur de santé du moteur RAG sur les 7 derniers jours. Valeur
              affichée = taux de feedback négatif. Sous-info = % de questions RH
              sans réponse trouvée + temps de réponse du cas le plus lent (5%
              des questions). Cliquez pour ouvrir la page Qualité.
            </>
          }
        />
        {session?.user?.staff_role !== "tech" ? (
          <>
            <KpiCard
              href="/admin/tools?tab=costs"
              title="Coût des questions (30 j)"
              icon={<DollarSign className="h-4 w-4" />}
              value={fmtCost(stats.cost_30d)}
              subValue="Hors ingestions et tests manuels"
              severity="neutral"
              help={
                <>
                  Coût total des appels API (OpenAI + Voyage AI) sur 30 jours,
                  uniquement pour les questions utilisateurs (les ingestions et
                  le bac à sable admin sont exclus).
                </>
              }
            />
          </>
        ) : (
          <KpiCard
            href="/admin/corpus?tab=updates"
            title="Mises à jour"
            icon={<RefreshCw className="size-4" />}
            value={String(stats.failed_syncs_24h)}
            subValue="Synchronisation(s) en échec sur 24 h"
            severity={stats.failed_syncs_24h > 0 ? "orange" : "neutral"}
          />
        )}
        <KpiCard
          href="/admin/corpus"
          title="Documents juridiques"
          icon={<Library className="h-4 w-4" />}
          value={`${stats.indexed_documents.toLocaleString("fr-FR")}`}
          subValue={`${stats.error_documents} erreur · ${stats.pending_documents} en attente`}
          severity={corpusSeverity}
          help={
            <>
              Nombre de documents communs indexés et interrogeables par le RAG
              (codes, conventions collectives, jurisprudence). Carte orange si
              docs en attente, rouge si docs en erreur.
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
              Nombre de questions posées dans le chat sur 7 jours, hors tests
              admin. <strong>Utilisateurs actifs</strong> = comptes ayant posé
              au moins 1 question récemment.
            </>
          }
        />
      </div>

      {/* Timeline chart */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            <TrendingUp className="h-4 w-4" />
            Questions par jour (30 jours)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <TimelineChart data={stats.questions_timeline_30d} />
        </CardContent>
      </Card>

      <details className="bg-card rounded-xl border p-5">
        <summary className="cursor-pointer text-sm font-semibold">
          Informations techniques et comptes
        </summary>
        <div className="mt-5">
          {/* Secondary info row */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-muted-foreground flex items-center gap-2 text-xs font-medium uppercase">
                  <Clock className="h-3 w-3" />
                  Dernière sync
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm font-medium">
                  {stats.last_sync_type ?? "—"}
                </div>
                <div className="text-muted-foreground mt-1 text-xs">
                  {fmtRelativeDate(stats.last_sync_at)}
                  {stats.last_sync_status && (
                    <Badge
                      variant="outline"
                      className={`ml-2 h-4 text-[10px] ${
                        ["ok", "success", "completed"].includes(
                          stats.last_sync_status.toLowerCase()
                        )
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
                <CardTitle className="text-muted-foreground flex items-center gap-2 text-xs font-medium uppercase">
                  <Cpu className="h-3 w-3" />
                  Modèle LLM
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="font-mono text-sm font-medium">
                  {stats.current_model}
                </div>
                {session?.user?.staff_role !== "tech" && (
                  <Link
                    href="/admin/tools?tab=costs"
                    className="text-muted-foreground mt-1 block text-xs hover:underline"
                  >
                    Réglages →
                  </Link>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-muted-foreground flex items-center gap-2 text-xs font-medium uppercase">
                  <Database className="h-3 w-3" />
                  Index Qdrant
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm font-medium">
                  {stats.total_chunks.toLocaleString("fr-FR")} chunks
                </div>
                <Link
                  href="/admin/tools?tab=index"
                  className="text-muted-foreground mt-1 block text-xs hover:underline"
                >
                  Inspecter →
                </Link>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-muted-foreground flex items-center gap-2 text-xs font-medium uppercase">
                  <Users className="h-3 w-3" />
                  Comptes
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm font-medium">
                  {stats.total_organisations} organisations ·{" "}
                  {stats.total_users} utilisateurs
                </div>
                {session?.user?.staff_role !== "tech" && (
                  <Link
                    href="/admin/users"
                    className="text-muted-foreground mt-1 block text-xs hover:underline"
                  >
                    Gérer →
                  </Link>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </details>
    </div>
  );
}
