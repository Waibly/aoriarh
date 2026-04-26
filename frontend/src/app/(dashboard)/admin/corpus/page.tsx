"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import {
  RefreshCw,
  Search,
  FlaskConical,
  Library,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Download,
  Trash2,
  Play,
  ChevronRight,
  Database,
  CalendarRange,
  Eye,
} from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { InfoTooltip } from "@/components/admin/info-tooltip";
import { InspectorBody, type InspectorPayload, type RagTrace, type CitedSource } from "../quality/InspectorBody";

// ----------------- Types -----------------

interface DocumentGroup {
  source_type: string;
  label: string;
  count: number;
  indexed: number;
  pending: number;
  total_chunks: number;
}

interface DocumentItem {
  id: string;
  name: string;
  source_type: string;
  indexation_status: string;
  file_size: number | null;
  created_at: string;
}

interface SyncLogItem {
  id: string;
  sync_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  items_fetched: number | null;
  items_created: number | null;
  items_updated: number | null;
  items_skipped: number | null;
  errors: number | null;
  error_message: string | null;
}

interface RetrievalResponse {
  answer: string | null;
  sources: CitedSource[];
  rag_trace: RagTrace;
  cost_usd: number;
  duration_ms: number;
}

// ----------------- Helpers -----------------

function fmtRelative(iso: string | null): string {
  if (!iso) return "jamais";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "à l'instant";
  if (mins < 60) return `il y a ${mins} min`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `il y a ${h} h`;
  const days = Math.floor(h / 24);
  return `il y a ${days} j`;
}

/**
 * Compute the next scheduled auto-sync date.
 * Cron: 1st and 15th of each month at 03:00 UTC.
 */
function nextAutoSync(): string {
  const now = new Date();
  // Try this month's 1st and 15th, then next month's 1st
  const candidates = [
    new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1, 3, 0, 0)),
    new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 15, 3, 0, 0)),
    new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1, 3, 0, 0)),
    new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 15, 3, 0, 0)),
  ];
  const next = candidates.find((d) => d.getTime() > now.getTime());
  if (!next) return "—";
  return next.toLocaleString("fr-FR", {
    weekday: "long",
    day: "2-digit",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Merge several SyncLog rows (a "batch" — typically the 6 jurisprudence
 * passes triggered by run_full_jurisprudence_sync) into a single synthetic
 * row that the SyncBanner can render as one card. Counters are summed,
 * timestamps span the whole batch, and status reflects the worst case
 * (running > error > success).
 */
function aggregateBatch(batch: SyncLogItem[]): SyncLogItem {
  if (batch.length === 1) return batch[0];
  const sortedByStart = [...batch].sort(
    (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  );
  const earliest = sortedByStart[0];
  const completedTimes = batch
    .map((r) => r.completed_at)
    .filter((c): c is string => !!c)
    .map((c) => new Date(c).getTime());
  const latestCompleted = completedTimes.length
    ? new Date(Math.max(...completedTimes)).toISOString()
    : null;
  const statuses = batch.map((r) => (r.status ?? "").toLowerCase());
  let status: string;
  if (statuses.some((s) => s === "running")) status = "running";
  else if (statuses.some((s) => ["error", "failed"].includes(s))) status = "error";
  else status = "success";
  const sum = (key: keyof SyncLogItem) =>
    batch.reduce((acc, r) => acc + ((r[key] as number | null) ?? 0), 0);
  const errorMessage =
    batch.find((r) => r.error_message)?.error_message ?? null;
  return {
    id: batch[0].id,
    sync_type: batch[0].sync_type,
    status,
    started_at: earliest.started_at,
    completed_at: latestCompleted,
    duration_ms: sum("duration_ms"),
    items_fetched: sum("items_fetched"),
    items_created: sum("items_created"),
    items_updated: sum("items_updated"),
    items_skipped: sum("items_skipped"),
    errors: sum("errors"),
    error_message: errorMessage,
  };
}

// ----------------- Live ingestion progress banner -----------------

interface CorpusHealth {
  docs_by_status: { [status: string]: number };
  docs_by_source_type: { [src: string]: number };
  common_total: number;
  pending_count: number;
  indexing_count: number;
  indexed_count: number;
  error_count: number;
  reserved_count: number;
  recent_sync_errors: {
    id: string;
    sync_type: string;
    started_at: string;
    error_message: string | null;
    duration_ms: number | null;
  }[];
  last_sync_per_type: { [t: string]: { status: string; started_at: string; items_created: number; items_fetched: number; errors: number } | null };
  is_busy: boolean;
}

function IngestionProgressBanner({ token }: { token: string }) {
  const [health, setHealth] = useState<CorpusHealth | null>(null);
  // Track the highest "in flight" count we've seen during the current
  // run so the progress bar reflects start → end of THIS batch and
  // doesn't shrink as new docs are enqueued.
  const [batchTotal, setBatchTotal] = useState<number | null>(null);
  const [batchStartedAt, setBatchStartedAt] = useState<number | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiFetch<CorpusHealth>("/admin/corpus/health", { token });
      setHealth(data);
    } catch {
      // silent — don't spam toasts on transient errors
    }
  }, [token]);

  // Initial load + 3s polling while busy
  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    if (!health?.is_busy) return;
    const i = setInterval(fetchHealth, 3000);
    return () => clearInterval(i);
  }, [health?.is_busy, fetchHealth]);

  // Track batch start
  useEffect(() => {
    if (!health) return;
    const inFlight = health.pending_count + health.indexing_count;
    if (inFlight > 0 && batchTotal === null) {
      setBatchTotal(inFlight);
      setBatchStartedAt(Date.now());
    } else if (inFlight === 0 && batchTotal !== null) {
      // Done — reset after a 4s linger so the user sees "100%"
      const t = setTimeout(() => {
        setBatchTotal(null);
        setBatchStartedAt(null);
      }, 4000);
      return () => clearTimeout(t);
    } else if (inFlight > (batchTotal ?? 0)) {
      // Bigger batch enqueued mid-flight — track the new total
      setBatchTotal(inFlight);
    }
  }, [health, batchTotal]);

  if (!health) return null;
  const inFlight = health.pending_count + health.indexing_count;
  const showBanner = inFlight > 0 || batchTotal !== null;
  if (!showBanner) return null;

  const total = batchTotal ?? inFlight;
  const done = Math.max(0, total - inFlight);
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;

  let etaLabel = "";
  if (batchStartedAt && done > 0 && inFlight > 0) {
    const elapsed = (Date.now() - batchStartedAt) / 1000;
    const rate = done / elapsed; // docs/sec
    if (rate > 0) {
      const remaining = inFlight / rate;
      if (remaining < 90) etaLabel = `~${Math.ceil(remaining)}s`;
      else if (remaining < 5400) etaLabel = `~${Math.ceil(remaining / 60)} min`;
      else etaLabel = `~${(remaining / 3600).toFixed(1)} h`;
    }
  }

  const isFinished = inFlight === 0 && batchTotal !== null;

  return (
    <Card
      className={`border-2 ${isFinished ? "border-green-400 bg-green-50/60 dark:bg-green-950/20" : "border-blue-400 bg-blue-50/60 dark:bg-blue-950/20"}`}
    >
      <CardContent className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            {isFinished ? (
              <CheckCircle2 className="h-4 w-4 text-green-600" />
            ) : (
              <Loader2 className="h-4 w-4 text-blue-600 animate-spin" />
            )}
            {isFinished
              ? "Indexation terminée"
              : `Indexation en cours… ${done.toLocaleString("fr-FR")} / ${total.toLocaleString("fr-FR")}`}
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {!isFinished && etaLabel && <span>ETA {etaLabel}</span>}
            <span className="font-mono">{pct}%</span>
          </div>
        </div>
        <div className="h-2 rounded bg-muted overflow-hidden">
          <div
            className={`h-full transition-all ${isFinished ? "bg-green-500" : "bg-blue-500"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="text-[10px] text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5">
          <span>en file : <span className="font-mono text-foreground">{health.pending_count}</span></span>
          <span>en cours : <span className="font-mono text-foreground">{health.indexing_count}</span></span>
          <span>indexés : <span className="font-mono text-foreground">{health.indexed_count.toLocaleString("fr-FR")}</span></span>
          {health.error_count > 0 && (
            <span className="text-red-600 dark:text-red-400">
              erreurs : <span className="font-mono">{health.error_count}</span>
            </span>
          )}
          <span>en réserve : <span className="font-mono text-foreground">{health.reserved_count.toLocaleString("fr-FR")}</span></span>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "indexed")
    return (
      <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-0">
        indexé
      </Badge>
    );
  if (status === "pending")
    return <Badge variant="outline">en attente</Badge>;
  if (status === "reserved")
    return (
      <Badge
        variant="outline"
        className="border-amber-300 text-amber-700 dark:text-amber-400"
        title="En réserve : sera ingéré quand une organisation installera la CCN correspondante"
      >
        en réserve
      </Badge>
    );
  if (status === "indexing")
    return (
      <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-0">
        <Loader2 className="h-3 w-3 mr-1 animate-spin" /> indexation
      </Badge>
    );
  if (status === "error")
    return (
      <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-0">
        erreur
      </Badge>
    );
  return <Badge variant="outline">{status}</Badge>;
}

// ----------------- Sync banner -----------------

function SyncBanner({ token, onRefresh }: { token: string; onRefresh: () => void }) {
  const [lastSyncs, setLastSyncs] = useState<{ [key: string]: SyncLogItem | null }>({});
  const [loading, setLoading] = useState(true);
  // running[key] = true while we wait for the trigger HTTP call to return
  const [running, setRunning] = useState<{ [key: string]: boolean }>({});
  // pollingIds[key] = id of the SyncLog row we're tracking (created right after trigger)
  const [pollingIds, setPollingIds] = useState<{ [key: string]: string | null }>({});

  const loadLastSyncs = useCallback(async () => {
    try {
      const data = await apiFetch<{ logs: SyncLogItem[]; total: number }>(
        "/admin/syncs/logs?page=1&page_size=50",
        { token },
      );
      // Map sync_type string -> UI key
      const keyOf = (t: string): string | null => {
        const tt = t.toLowerCase();
        if (tt === "kali" || tt === "ccn") return "kali";
        if (tt === "jurisprudence" || tt === "judilibre") return "judilibre";
        if (tt === "codes" || tt === "code_travail") return "code_travail";
        if (tt === "bocc") return "bocc";
        return null;
      };
      // Group all logs per key, then aggregate the most recent "batch"
      // (= rows started within 30 min of the most recent row of that key).
      // This is necessary because a single manual trigger like
      // run_full_jurisprudence_sync writes 6 SyncLog rows (one per pass)
      // and we want to display them as a single aggregated card.
      const grouped: { [key: string]: SyncLogItem[] } = {
        kali: [],
        judilibre: [],
        code_travail: [],
        bocc: [],
      };
      for (const log of data.logs) {
        const key = keyOf(log.sync_type);
        if (key) grouped[key].push(log);
      }
      const WINDOW_MS = 30 * 60 * 1000;
      const byKey: { [key: string]: SyncLogItem | null } = {
        kali: null,
        judilibre: null,
        code_travail: null,
        bocc: null,
      };
      for (const key of Object.keys(grouped)) {
        const rows = grouped[key];
        if (rows.length === 0) continue;
        // logs come back ordered most-recent first
        const mostRecent = rows[0];
        const refMs = new Date(mostRecent.started_at).getTime();
        const batch = rows.filter(
          (r) => refMs - new Date(r.started_at).getTime() <= WINDOW_MS,
        );
        byKey[key] = aggregateBatch(batch);
      }
      setLastSyncs(byKey);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadLastSyncs();
  }, [loadLastSyncs]);

  // Poll while at least one job is being tracked
  useEffect(() => {
    const trackedKeys = Object.entries(pollingIds).filter(([, id]) => id !== null);
    if (trackedKeys.length === 0) return;
    const interval = setInterval(() => {
      loadLastSyncs();
    }, 3000);
    return () => clearInterval(interval);
  }, [pollingIds, loadLastSyncs]);

  // Detect when a tracked job finishes. We poll on the aggregated status:
  // a multi-pass batch (e.g. jurisprudence × 6) is "running" until none of
  // the rows in the time window are in the running state anymore.
  useEffect(() => {
    Object.entries(pollingIds).forEach(([key, marker]) => {
      if (!marker) return;
      const log = lastSyncs[key];
      if (!log) return;
      const status = (log.status ?? "").toLowerCase();
      const finished = ["ok", "success", "completed", "error", "failed"].includes(status);
      if (finished) {
        setPollingIds((prev) => ({ ...prev, [key]: null }));
        const isOk = ["ok", "success", "completed"].includes(status);
        if (isOk) {
          toast.success(
            `Sync ${key} terminée — ${log.items_created ?? 0} créé(s), ${
              log.items_fetched ?? 0
            } récupéré(s)`,
          );
        } else {
          toast.error(`Sync ${key} échouée : ${log.error_message ?? "erreur"}`);
        }
        onRefresh();
      }
    });
  }, [lastSyncs, pollingIds, onRefresh]);

  const triggerSync = async (key: string) => {
    setRunning((prev) => ({ ...prev, [key]: true }));
    try {
      let path = "";
      if (key === "kali") path = "/admin/ccn/sync-all";
      else if (key === "code_travail") path = "/admin/syncs/codes";
      else if (key === "bocc") path = "/admin/syncs/bocc";
      else if (key === "judilibre") path = "/admin/jurisprudence/sync-all";

      await apiFetch(path, {
        method: "POST",
        token,
        headers: { "Content-Type": "application/json" },
      });
      toast.info(`Sync ${key} lancée — suivi en cours…`);
      // Refresh logs to capture the freshly created sync_log entry
      await loadLastSyncs();
      // Find the most recent log for this key (just created) and start tracking it
      const fresh = await apiFetch<{ logs: SyncLogItem[]; total: number }>(
        "/admin/syncs/logs?page=1&page_size=10",
        { token },
      );
      const matcher = (t: string) => {
        const tt = t.toLowerCase();
        if (key === "kali") return tt === "kali" || tt === "ccn";
        if (key === "judilibre") return tt === "jurisprudence" || tt === "judilibre";
        if (key === "code_travail") return tt === "codes" || tt === "code_travail";
        if (key === "bocc") return tt === "bocc";
        return false;
      };
      const freshest = fresh.logs.find((l) => matcher(l.sync_type));
      // Use a sentinel marker (not the row id) since aggregation may
      // pick a different id every poll cycle as new passes start.
      if (freshest) {
        setPollingIds((prev) => ({ ...prev, [key]: freshest.id }));
      } else {
        setPollingIds((prev) => ({ ...prev, [key]: "pending" }));
      }
    } catch {
      toast.error("Échec du déclenchement de la sync");
    } finally {
      setRunning((prev) => ({ ...prev, [key]: false }));
    }
  };

  const sources = [
    {
      key: "kali",
      label: "KALI (CCN)",
      auto: true,
      autoDetail: "Rotation des 15 CCN installées les plus anciennement synchronisées",
      help: "Synchronise les conventions collectives nationales depuis la base KALI de Légifrance. Met à jour le contenu des CCN installées dans les organisations.",
    },
    {
      key: "judilibre",
      label: "Jurisprudence",
      auto: true,
      autoDetail: "Cass. soc / cr / comm / civ2 + CA chambre sociale (cap 300) + Conseil constit",
      help: "Récupère les arrêts récents de la jurisprudence sociale française : Cour de cassation (chambres sociale, criminelle, commerciale, 2e civile pour AT/MP), Cour d'appel chambre sociale (filtrée à ~300 arrêts les plus récents) et Conseil constitutionnel. Fenêtre de 30 jours, exécuté à chaque sync.",
    },
    {
      key: "code_travail",
      label: "Codes",
      auto: true,
      autoDetail: "9 codes (travail, civil, pénal, CSS, action sociale, santé publique, commerce, monétaire et financier, CGI). Hash SHA-256 — réingéré uniquement si différent.",
      help: "Récupère et met à jour les 9 codes juridiques pertinents : Code du travail, Code civil, Code pénal, Code de la sécurité sociale, Code de l'action sociale et des familles, Code de la santé publique, Code de commerce, Code monétaire et financier, Code général des impôts. Seuls les codes dont le contenu Légifrance a changé sont réingérés.",
    },
    {
      key: "bocc",
      label: "BOCC",
      auto: true,
      autoDetail: "1 numéro à chaque exécution (semaine en cours - 2)",
      help: "Bulletin Officiel des Conventions Collectives — récupère les nouveaux avenants publiés. Ils sont mis en réserve et ingérés automatiquement à l'installation de la CCN concernée.",
    },
  ];

  return (
    <Card>
      <div className="flex items-center justify-between px-4 pt-3 pb-2 border-b">
        <div className="flex items-center gap-2 text-xs font-semibold">
          Synchronisations
          <InfoTooltip>
            <strong>Synchronisation automatique</strong> bimensuelle :
            les <strong>1er et 15</strong> de chaque mois à <strong>03:00 UTC</strong>.
            <br />
            Inclus : KALI (rotation 15 CCN), Jurisprudence 30j (Cass soc/cr/comm/civ2 + CA ch. soc + Conseil constit),
            BOCC (1 numéro), 9 codes (hash SHA-256).
            <br />
            Pour les codes, un hash SHA-256 du contenu est comparé à la
            version stockée : si identique, rien n&apos;est réingéré (zéro
            coût d&apos;embeddings).
          </InfoTooltip>
        </div>
        <div className="text-[10px] text-muted-foreground">
          Prochaine sync auto : <span className="font-medium text-foreground">{nextAutoSync()}</span>
        </div>
      </div>
      <CardContent className="p-3 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2">
        {sources.map((s) => {
          const log = lastSyncs[s.key];
          const isPolling = pollingIds[s.key] !== null && pollingIds[s.key] !== undefined;
          const isTriggering = running[s.key] === true;
          const isRunning = isPolling || isTriggering;
          const status = log?.status?.toLowerCase() ?? "";
          const ok = ["ok", "success", "completed"].includes(status);
          const isErr = ["error", "failed"].includes(status);
          // "Soft" warnings: unchanged content (hash skip) or upstream-not-ready
          const isUpToDate =
            ok &&
            log?.items_skipped !== null &&
            (log?.items_skipped ?? 0) > 0 &&
            (log?.items_created ?? 0) === 0;
          // BOCC may report 'Archive ... introuvable' which is a DILA delay,
          // not a real error from our side — render as a warning, not red.
          const isUpstreamMissing =
            isErr && (log?.error_message ?? "").toLowerCase().includes("introuvable");
          const cardBorder = isRunning
            ? "border-blue-300 bg-blue-50/50 dark:bg-blue-950/20"
            : isUpstreamMissing
            ? "border-amber-300 bg-amber-50/50 dark:bg-amber-950/20"
            : "";

          return (
            <div
              key={s.key}
              className={`flex flex-col gap-1 border rounded-md p-3 text-xs transition-colors ${cardBorder}`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 min-w-0">
                  {loading ? (
                    <Skeleton className="h-3 w-3" />
                  ) : isRunning ? (
                    <Loader2 className="h-3 w-3 text-blue-600 animate-spin" />
                  ) : log ? (
                    ok ? (
                      <CheckCircle2 className="h-3 w-3 text-green-600" />
                    ) : isUpstreamMissing ? (
                      <AlertCircle className="h-3 w-3 text-amber-600" />
                    ) : isErr ? (
                      <AlertCircle className="h-3 w-3 text-red-600" />
                    ) : (
                      <Loader2 className="h-3 w-3 text-blue-600 animate-spin" />
                    )
                  ) : (
                    <span className="h-3 w-3 inline-block rounded-full bg-muted-foreground/30" />
                  )}
                  <span className="font-medium truncate">{s.label}</span>
                  {s.auto ? (
                    <Badge
                      variant="outline"
                      className="text-[9px] h-4 px-1 border-green-300 text-green-700 dark:text-green-400 shrink-0"
                      title={s.autoDetail ?? undefined}
                    >
                      auto
                    </Badge>
                  ) : (
                    <Badge
                      variant="outline"
                      className="text-[9px] h-4 px-1 border-amber-300 text-amber-700 dark:text-amber-400 shrink-0"
                    >
                      manuel
                    </Badge>
                  )}
                  <InfoTooltip>{s.help}</InfoTooltip>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={isRunning}
                  onClick={() => triggerSync(s.key)}
                  className="h-7 px-2 text-[11px] shrink-0"
                  title="Lancer la sync"
                >
                  {isRunning ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3 w-3" />
                  )}
                </Button>
              </div>

              {/* Status line */}
              <div className="text-muted-foreground text-[10px] truncate min-h-[14px]">
                {isRunning
                  ? "En cours..."
                  : log
                  ? `${fmtRelative(log.started_at)}${
                      log.duration_ms ? ` · ${(log.duration_ms / 1000).toFixed(0)}s` : ""
                    }`
                  : "—"}
              </div>

              {/* Progress / counts (visible when running OR after completion) */}
              {log && (
                <div className="text-[10px] flex flex-wrap gap-x-2 gap-y-0.5">
                  {isUpToDate ? (
                    <span className="text-green-700 dark:text-green-400 font-medium">
                      ✓ déjà à jour
                      {log.items_fetched !== null && log.items_fetched > 0 && (
                        <span className="text-muted-foreground font-normal">
                          {" "}
                          ({log.items_fetched.toLocaleString("fr-FR")} vérifiés)
                        </span>
                      )}
                    </span>
                  ) : (
                    <>
                      {log.items_fetched !== null && log.items_fetched > 0 && (
                        <span className="text-muted-foreground">
                          <span className="font-mono font-semibold text-foreground">
                            {log.items_fetched.toLocaleString("fr-FR")}
                          </span>{" "}
                          récupéré
                        </span>
                      )}
                      {log.items_created !== null && log.items_created > 0 && (
                        <span className="text-muted-foreground">
                          <span className="font-mono font-semibold text-foreground">
                            {log.items_created.toLocaleString("fr-FR")}
                          </span>{" "}
                          créé
                        </span>
                      )}
                    </>
                  )}
                  {log.errors !== null && log.errors > 0 && (
                    <span className="text-red-600 dark:text-red-400">
                      <span className="font-mono font-semibold">{log.errors}</span>{" "}
                      erreur
                    </span>
                  )}
                </div>
              )}

              {/* Soft error: upstream missing (DILA delay etc.) */}
              {isUpstreamMissing && log?.error_message && (
                <div
                  className="text-[10px] text-amber-700 dark:text-amber-400 truncate"
                  title={`${log.error_message}\n\nLa source externe n'a pas encore publié cette donnée. Réessayez plus tard.`}
                >
                  ⏳ Source externe pas encore disponible
                </div>
              )}

              {/* Hard error message */}
              {isErr && !isUpstreamMissing && log?.error_message && (
                <div className="text-[10px] text-red-600 dark:text-red-400 truncate" title={log.error_message}>
                  {log.error_message}
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ----------------- Test retrieval modal -----------------

function TestRetrievalDialog({
  open,
  onOpenChange,
  token,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
}) {
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RetrievalResponse | null>(null);

  const handleRun = async () => {
    if (!query.trim()) {
      toast.error("Saisis une question");
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const data = await apiFetch<RetrievalResponse>("/admin/corpus/test-retrieval", {
        method: "POST",
        token,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
      });
      setResult(data);
    } catch {
      toast.error("Échec du test");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4" />
            Tester la recherche dans le corpus commun
          </DialogTitle>
          <DialogDescription>
            Lance la recherche RAG (hybride + rerank + parent expansion) sans appeler le LLM.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Que dit l'article L4121-1 du code du travail ?"
            rows={3}
          />
          <Button onClick={handleRun} disabled={running} className="w-full">
            <Play className="h-4 w-4 mr-2" />
            {running ? "Exécution..." : "Lancer le test"}
          </Button>
        </div>

        {result && (
          <div className="mt-4">
            <InspectorBody
              data={{
                question: query,
                answer: result.answer,
                sources: result.sources,
                rag_trace: result.rag_trace,
                cost_usd: result.cost_usd,
                latency_ms: result.duration_ms,
              } as InspectorPayload}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ----------------- Main page -----------------

export default function CorpusPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [groups, setGroups] = useState<DocumentGroup[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [testOpen, setTestOpen] = useState(false);

  const fetchGroups = useCallback(async () => {
    if (!token) return;
    setGroupsLoading(true);
    try {
      const data = await apiFetch<{ groups: DocumentGroup[] }>(
        "/admin/documents/groups",
        { token },
      );
      setGroups(data.groups);
      if (!selectedType && data.groups.length > 0) {
        setSelectedType(data.groups[0].source_type);
      }
    } catch {
      toast.error("Erreur lors du chargement des catégories");
    } finally {
      setGroupsLoading(false);
    }
  }, [token, selectedType]);

  const fetchDocs = useCallback(async () => {
    if (!token || !selectedType || selectedType === "bocc_reserve") {
      setDocs([]);
      return;
    }
    setDocsLoading(true);
    try {
      const data = await apiFetch<DocumentItem[]>(
        `/admin/documents/groups/${selectedType}?page=1&page_size=200`,
        { token },
      );
      setDocs(data);
    } catch {
      toast.error("Erreur lors du chargement des documents");
    } finally {
      setDocsLoading(false);
    }
  }, [token, selectedType]);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  const handleReindex = async (id: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/documents/${id}/reindex`, { method: "POST", token });
      toast.success("Réindexation lancée");
      setTimeout(fetchDocs, 1000);
    } catch {
      toast.error("Échec");
    }
  };

  const [reindexAllRunning, setReindexAllRunning] = useState(false);
  const handleReindexAll = async () => {
    if (!token) return;
    if (
      !confirm(
        "Réindexer TOUS les documents du corpus commun ? Cette opération " +
          "peut prendre ~30 minutes et consomme du budget embeddings.",
      )
    )
      return;
    setReindexAllRunning(true);
    try {
      const data = await apiFetch<{ enqueued: number; skipped: number }>(
        "/admin/documents/actions/reindex-all",
        { method: "POST", token },
      );
      toast.success(
        `Réindexation lancée — ${data.enqueued} document(s) en file, ${data.skipped} ignoré(s)`,
      );
      setTimeout(fetchGroups, 2000);
    } catch {
      toast.error("Échec du déclenchement");
    } finally {
      setReindexAllRunning(false);
    }
  };

  // ---------- Synchronisation personnalisée (plage de dates choisie) ----------
  const [customSyncOpen, setCustomSyncOpen] = useState(false);
  const [customSource, setCustomSource] = useState<string>("cass_soc");
  const [customDateStart, setCustomDateStart] = useState<string>("2005-01-01");
  const [customDateEnd, setCustomDateEnd] = useState<string>(
    new Date().toISOString().slice(0, 10),
  );
  const [customMaxDecisions, setCustomMaxDecisions] = useState<string>("");
  const [customPreview, setCustomPreview] = useState<{
    total: number;
    warning: string | null;
    label: string;
  } | null>(null);
  const [customPreviewLoading, setCustomPreviewLoading] = useState(false);
  const [customSyncRunning, setCustomSyncRunning] = useState(false);

  const customSourceOptions: { value: string; label: string }[] = [
    { value: "cass_soc", label: "Cass. soc (chambre sociale)" },
    { value: "cass_cr", label: "Cass. crim (chambre criminelle)" },
    { value: "cass_comm", label: "Cass. com (chambre commerciale)" },
    { value: "cass_civ2", label: "Cass. civ2 (sécurité sociale / AT-MP)" },
    { value: "ca_soc", label: "Cour d'appel — chambre sociale" },
    { value: "conseil_constit", label: "Conseil constitutionnel" },
  ];

  // Dès qu'un champ change, on invalide le preview (forcer un nouveau clic)
  useEffect(() => {
    setCustomPreview(null);
  }, [customSource, customDateStart, customDateEnd]);

  const handleCustomPreview = async () => {
    if (!token) return;
    if (customDateStart > customDateEnd) {
      toast.error("La date de début doit être antérieure ou égale à la date de fin.");
      return;
    }
    setCustomPreviewLoading(true);
    try {
      const params = new URLSearchParams({
        source: customSource,
        date_start: customDateStart,
        date_end: customDateEnd,
      });
      const data = await apiFetch<{
        total: number;
        source_label: string;
        warning: string | null;
      }>(`/admin/jurisprudence/preview?${params.toString()}`, { token });
      setCustomPreview({
        total: data.total,
        warning: data.warning,
        label: data.source_label,
      });
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Échec de l'aperçu Judilibre",
      );
    } finally {
      setCustomPreviewLoading(false);
    }
  };

  const handleCustomSync = async () => {
    if (!token) return;
    if (customDateStart > customDateEnd) {
      toast.error("La date de début doit être antérieure ou égale à la date de fin.");
      return;
    }

    // Confirmation modale si plage > 3 ans ou volume > 3 000 arrêts
    const yearsSpan =
      (new Date(customDateEnd).getTime() - new Date(customDateStart).getTime()) /
      (1000 * 60 * 60 * 24 * 365.25);
    const bigVolume = (customPreview?.total ?? 0) > 3000;
    const wideRange = yearsSpan > 3;
    if (bigVolume || wideRange) {
      const reasons: string[] = [];
      if (customPreview)
        reasons.push(`Volume Judilibre : ${customPreview.total.toLocaleString("fr-FR")} arrêts`);
      if (wideRange) reasons.push(`Plage : ${yearsSpan.toFixed(1)} ans`);
      if (
        !confirm(
          `Lancer la synchronisation ?\n\n${reasons.join("\n")}\n\n` +
            "Cette opération peut prendre plusieurs heures et consomme du budget embeddings " +
            "(Voyage AI ≈ 0,12 €/M tokens).\n\nContinuer ?",
        )
      )
        return;
    }

    setCustomSyncRunning(true);
    try {
      const max = customMaxDecisions.trim()
        ? parseInt(customMaxDecisions.trim(), 10)
        : null;
      await apiFetch("/admin/jurisprudence/sync-custom", {
        method: "POST",
        token,
        body: JSON.stringify({
          source: customSource,
          date_start: customDateStart,
          date_end: customDateEnd,
          max_decisions: Number.isFinite(max) && max && max > 0 ? max : null,
        }),
      });
      toast.success(
        "Synchronisation lancée — suis l'avancement dans le bandeau ci-dessous.",
      );
      setCustomSyncOpen(false);
      // SyncBanner polls itself, so we juste refresh the document groups to
      // pick up the freshly enqueued items.
      setTimeout(() => {
        fetchGroups();
      }, 1500);
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : "Échec du déclenchement de la sync",
      );
    } finally {
      setCustomSyncRunning(false);
    }
  };

  const [initJurisRunning, setInitJurisRunning] = useState(false);
  const handleInitJurisprudence = async () => {
    if (!token) return;
    if (
      !confirm(
        "INITIALISATION du corpus jurisprudence — opération one-shot.\n\n" +
          "• Cass. soc / cr / comm / civ2 publiés sur 1 an (~1 500 arrêts)\n" +
          "• Cour d'appel chambre sociale sur 3 mois (cap 3 000)\n\n" +
          "Idempotent (la dédup par numéro de pourvoi évite les doublons).\n" +
          "Coût embeddings estimé : ~10 $.\n\n" +
          "Continuer ?",
      )
    )
      return;
    setInitJurisRunning(true);
    try {
      await apiFetch("/admin/jurisprudence/initialize", {
        method: "POST",
        token,
      });
      toast.success(
        "Initialisation jurisprudence lancée — suis l'avancement dans le bandeau.",
      );
    } catch {
      toast.error("Échec du déclenchement");
    } finally {
      setInitJurisRunning(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!token) return;
    if (!confirm(`Supprimer "${name}" ?`)) return;
    try {
      await apiFetch(`/admin/documents/${id}`, { method: "DELETE", token });
      toast.success("Supprimé");
      fetchDocs();
      fetchGroups();
    } catch {
      toast.error("Échec");
    }
  };

  const filteredDocs = useMemo(() => {
    return docs.filter((d) => {
      if (statusFilter !== "all" && d.indexation_status !== statusFilter) return false;
      if (search.trim() && !d.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [docs, search, statusFilter]);

  if (!token) return null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Corpus juridique</h1>
          <p className="text-sm text-muted-foreground">
            Tous les documents communs : codes, conventions collectives, jurisprudence, doctrine.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setCustomSyncOpen(true)}
            title="Synchroniser la jurisprudence sur une plage de dates choisie"
          >
            <CalendarRange className="h-4 w-4 mr-2" />
            Sync personnalisée
          </Button>
          <Button
            variant="outline"
            onClick={handleInitJurisprudence}
            disabled={initJurisRunning}
            title="Initialise le corpus jurisprudence (one-shot)"
          >
            {initJurisRunning ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Database className="h-4 w-4 mr-2" />
            )}
            Init jurisprudence
          </Button>
          <Button
            variant="outline"
            onClick={handleReindexAll}
            disabled={reindexAllRunning}
            title="Réindexer tous les documents du corpus commun"
          >
            {reindexAllRunning ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Tout réindexer
          </Button>
          <Button variant="outline" onClick={() => setTestOpen(true)}>
            <FlaskConical className="h-4 w-4 mr-2" />
            Tester recherche
          </Button>
          <InfoTooltip side="bottom">
            Lance la recherche RAG (hybride + rerank + parent expansion) sur
            le corpus commun, sans appeler le LLM. Permet de vérifier que
            les bons chunks remontent pour une question donnée.
          </InfoTooltip>
          <Button variant="outline" size="sm" onClick={fetchGroups}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Live ingestion progress (visible only when worker is busy) */}
      <IngestionProgressBanner token={token} />

      {/* Sync banner */}
      <SyncBanner token={token} onRefresh={fetchGroups} />

      {/* Main: sidebar + table */}
      <div className="grid grid-cols-12 gap-4">
        {/* Sidebar categories */}
        <div className="col-span-12 md:col-span-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Library className="h-4 w-4" />
                Catégories
              </CardTitle>
            </CardHeader>
            <CardContent className="p-2">
              {groupsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
                </div>
              ) : (
                <div className="space-y-1">
                  {groups.map((g) => {
                    const active = selectedType === g.source_type;
                    return (
                      <button
                        key={g.source_type}
                        onClick={() => setSelectedType(g.source_type)}
                        className={`w-full text-left px-2 py-2 rounded text-sm flex items-center justify-between gap-2 transition-colors ${
                          active ? "bg-accent text-accent-foreground" : "hover:bg-muted/50"
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-medium truncate text-xs">{g.label}</div>
                          <div className="text-[10px] text-muted-foreground">
                            {g.indexed} indexés
                            {g.pending > 0 && ` · ${g.pending} en attente`}
                          </div>
                        </div>
                        <ChevronRight className="h-3 w-3 shrink-0" />
                      </button>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Documents table */}
        <div className="col-span-12 md:col-span-9 space-y-3">
          <div className="flex flex-col md:flex-row gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Rechercher par nom de document..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les statuts</SelectItem>
                <SelectItem value="indexed">Indexés</SelectItem>
                <SelectItem value="pending">En attente</SelectItem>
                <SelectItem value="indexing">En cours</SelectItem>
                <SelectItem value="error">En erreur</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Card>
            <CardContent>
              {docsLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : filteredDocs.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  Aucun document dans cette catégorie pour ces filtres.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Nom</TableHead>
                      <TableHead className="w-[110px]">Statut</TableHead>
                      <TableHead className="w-[80px] text-right">Taille</TableHead>
                      <TableHead className="w-[100px] text-right">Date</TableHead>
                      <TableHead className="w-[140px]"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredDocs.map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="text-sm font-medium max-w-md break-words whitespace-normal align-top">
                          {d.name}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={d.indexation_status} />
                        </TableCell>
                        <TableCell className="text-right text-xs text-muted-foreground">
                          {fmtSize(d.file_size)}
                        </TableCell>
                        <TableCell className="text-right text-xs text-muted-foreground">
                          {new Date(d.created_at).toLocaleDateString("fr-FR")}
                        </TableCell>
                        <TableCell>
                          <div className="flex gap-1 justify-end">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleReindex(d.id)}
                              title="Réindexer"
                            >
                              <RefreshCw className="h-3 w-3" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              asChild
                              title="Télécharger"
                            >
                              <a href={`/api/v1/admin/documents/${d.id}/download`}>
                                <Download className="h-3 w-3" />
                              </a>
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDelete(d.id, d.name)}
                              title="Supprimer"
                              className="text-red-600 hover:text-red-700"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <TestRetrievalDialog open={testOpen} onOpenChange={setTestOpen} token={token} />

      {/* ---------- Synchronisation jurisprudence personnalisée ---------- */}
      <Dialog open={customSyncOpen} onOpenChange={setCustomSyncOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CalendarRange className="h-5 w-5" />
              Synchronisation jurisprudence personnalisée
            </DialogTitle>
            <DialogDescription>
              Récupère les arrêts d&apos;une source juridique sur la plage de dates de
              votre choix. Idempotent : les arrêts déjà ingérés (dédup par numéro
              de pourvoi) ne sont pas dupliqués.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Source */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Source</label>
              <Select value={customSource} onValueChange={setCustomSource}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {customSourceOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Dates */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Du</label>
                <Input
                  type="date"
                  value={customDateStart}
                  onChange={(e) => setCustomDateStart(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Au</label>
                <Input
                  type="date"
                  value={customDateEnd}
                  onChange={(e) => setCustomDateEnd(e.target.value)}
                />
              </div>
            </div>

            {/* Plafond (optionnel) */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">
                Plafond <span className="text-muted-foreground font-normal">(optionnel)</span>
              </label>
              <Input
                type="number"
                placeholder="Aucun (recommandé pour Cassation)"
                value={customMaxDecisions}
                onChange={(e) => setCustomMaxDecisions(e.target.value)}
                min={1}
              />
              <p className="text-xs text-muted-foreground">
                Limite le nombre d&apos;arrêts ingérés. Utile pour les Cours d&apos;appel
                (~80 % filtrés sur la chambre, volume très élevé).
              </p>
            </div>

            {/* Aperçu */}
            <div className="rounded-md border bg-muted/30 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">Aperçu Judilibre</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCustomPreview}
                  disabled={customPreviewLoading}
                >
                  {customPreviewLoading ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : (
                    <Eye className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  Calculer
                </Button>
              </div>
              {customPreview ? (
                <div className="space-y-1">
                  <div className="text-sm">
                    <span className="font-semibold">
                      {customPreview.total.toLocaleString("fr-FR")}
                    </span>{" "}
                    arrêts disponibles pour cette plage.
                  </div>
                  {customPreview.warning && (
                    <div className="flex gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                      <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                      <span>{customPreview.warning}</span>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Cliquez sur « Calculer » pour interroger Judilibre avant de
                  lancer la synchronisation.
                </p>
              )}
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => setCustomSyncOpen(false)}
              disabled={customSyncRunning}
            >
              Annuler
            </Button>
            <Button onClick={handleCustomSync} disabled={customSyncRunning}>
              {customSyncRunning ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Play className="h-4 w-4 mr-2" />
              )}
              Lancer la synchronisation
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
