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
  duration_ms: number | null;
  items_fetched: number | null;
  items_created: number | null;
  errors_count: number | null;
  error_message: string | null;
}

interface RetrievalChunk {
  document_id: string;
  doc_name: string;
  chunk_index: number;
  score: number;
  source_type: string;
  text_preview: string;
}

interface RetrievalResponse {
  query: string;
  duration_ms: number;
  chunks_hybrid: RetrievalChunk[];
  chunks_reranked: RetrievalChunk[];
  chunks_expanded: RetrievalChunk[];
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

function StatusBadge({ status }: { status: string }) {
  if (status === "indexed")
    return (
      <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-0">
        indexé
      </Badge>
    );
  if (status === "pending")
    return <Badge variant="outline">en attente</Badge>;
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
      // Group: keep the most recent log per sync_type prefix
      const byKey: { [key: string]: SyncLogItem | null } = {
        kali: null,
        judilibre: null,
        code_travail: null,
        bocc: null,
      };
      for (const log of data.logs) {
        const t = log.sync_type.toLowerCase();
        let key: string | null = null;
        if (t.includes("kali") || t.includes("ccn")) key = "kali";
        else if (t.includes("juris") || t.includes("judilibre")) key = "judilibre";
        else if (t.includes("code")) key = "code_travail";
        else if (t.includes("bocc")) key = "bocc";
        if (key && !byKey[key]) byKey[key] = log;
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

  // Detect when a tracked job finishes (status changes from running to ok/error)
  useEffect(() => {
    Object.entries(pollingIds).forEach(([key, id]) => {
      if (!id) return;
      const log = lastSyncs[key];
      if (!log) return;
      if (log.id === id) {
        const finished =
          log.status &&
          ["ok", "success", "completed", "error", "failed"].includes(
            log.status.toLowerCase()
          );
        if (finished) {
          setPollingIds((prev) => ({ ...prev, [key]: null }));
          const isOk = ["ok", "success", "completed"].includes(
            log.status.toLowerCase()
          );
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
      }
    });
  }, [lastSyncs, pollingIds, onRefresh]);

  const triggerSync = async (key: string) => {
    setRunning((prev) => ({ ...prev, [key]: true }));
    try {
      let path = "";
      if (key === "kali") path = "/admin/ccn/sync-all";
      else if (key === "code_travail") path = "/admin/syncs/code-travail";
      else if (key === "bocc") path = "/admin/syncs/bocc";
      else if (key === "judilibre") path = "/admin/jurisprudence/sync";

      await apiFetch(path, {
        method: "POST",
        token,
        headers: { "Content-Type": "application/json" },
        body: key === "judilibre" ? JSON.stringify({}) : undefined,
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
        if (key === "kali") return tt.includes("kali") || tt.includes("ccn");
        if (key === "judilibre") return tt.includes("juris") || tt.includes("judilibre");
        if (key === "code_travail") return tt.includes("code");
        if (key === "bocc") return tt.includes("bocc");
        return false;
      };
      const freshest = fresh.logs.find((l) => matcher(l.sync_type));
      if (freshest) {
        setPollingIds((prev) => ({ ...prev, [key]: freshest.id }));
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
      label: "Judilibre",
      auto: true,
      autoDetail: "Derniers 30 jours, chambre sociale, publication B",
      help: "Récupère les arrêts de la Cour de cassation depuis l'API Judilibre (PISTE). Permet d'enrichir le corpus jurisprudentiel.",
    },
    {
      key: "code_travail",
      label: "Code travail",
      auto: true,
      autoDetail: "Hash SHA-256 comparé à la version stockée — réingéré uniquement si différent",
      help: "Récupère et met à jour le Code du travail consolidé depuis Légifrance (parties législative et réglementaire). Inclus dans la sync automatique bimensuelle ; seul un changement de contenu déclenche une nouvelle ingestion.",
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
            Inclus : KALI (rotation 15 CCN), Judilibre (30j), BOCC (1 numéro),
            <strong> Code du travail</strong>, codes civil / pénal / CSS / CASF.
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

          return (
            <div
              key={s.key}
              className={`flex flex-col gap-1 border rounded-md p-3 text-xs transition-colors ${
                isRunning ? "border-blue-300 bg-blue-50/50 dark:bg-blue-950/20" : ""
              }`}
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
              {log && (log.items_fetched !== null || log.items_created !== null) && (
                <div className="text-[10px] flex flex-wrap gap-x-2 gap-y-0.5">
                  {log.items_fetched !== null && (
                    <span className="text-muted-foreground">
                      <span className="font-mono font-semibold text-foreground">
                        {log.items_fetched}
                      </span>{" "}
                      récupéré
                    </span>
                  )}
                  {log.items_created !== null && (
                    <span className="text-muted-foreground">
                      <span className="font-mono font-semibold text-foreground">
                        {log.items_created}
                      </span>{" "}
                      créé
                    </span>
                  )}
                  {log.errors_count !== null && log.errors_count > 0 && (
                    <span className="text-red-600 dark:text-red-400">
                      <span className="font-mono font-semibold">{log.errors_count}</span>{" "}
                      erreur
                    </span>
                  )}
                </div>
              )}

              {/* Error message if failed */}
              {isErr && log?.error_message && (
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
          <div className="space-y-4 mt-4">
            <div className="text-xs text-muted-foreground">
              Durée : <span className="font-mono">{result.duration_ms} ms</span>
            </div>

            <div>
              <h3 className="text-sm font-semibold mb-2">
                Sources finales envoyées au LLM ({result.chunks_expanded.length})
              </h3>
              <div className="space-y-2">
                {result.chunks_expanded.map((c, i) => (
                  <ChunkRow key={`exp-${i}`} chunk={c} rank={i + 1} />
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold mb-2">
                Top après rerank ({result.chunks_reranked.length})
              </h3>
              <div className="space-y-2">
                {result.chunks_reranked.map((c, i) => (
                  <ChunkRow key={`rk-${i}`} chunk={c} rank={i + 1} />
                ))}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold mb-2">
                Pool initial avant rerank ({result.chunks_hybrid.length})
              </h3>
              <div className="space-y-2">
                {result.chunks_hybrid.map((c, i) => (
                  <ChunkRow key={`h-${i}`} chunk={c} rank={i + 1} />
                ))}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ChunkRow({ chunk, rank }: { chunk: RetrievalChunk; rank: number }) {
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
                        <TableCell className="text-sm font-medium truncate max-w-md">
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
    </div>
  );
}
