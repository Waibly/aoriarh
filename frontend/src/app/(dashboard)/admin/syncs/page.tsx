"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { RefreshCw, Play, CheckCircle2, XCircle, MinusCircle, Clock, BookOpen } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface SyncLog {
  id: string;
  sync_type: string;
  idcc: string | null;
  status: string;
  items_fetched: number;
  items_created: number;
  items_updated: number;
  items_skipped: number;
  errors: number;
  error_message: string | null;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
}

interface SyncLogsResponse {
  logs: SyncLog[];
  total: number;
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "success":
      return (
        <Badge variant="outline" className="rounded-full border-green-500 bg-green-500/10 text-green-700 text-xs">
          <CheckCircle2 className="mr-1 h-3 w-3" />
          Succès
        </Badge>
      );
    case "error":
      return (
        <Badge variant="outline" className="rounded-full border-destructive bg-destructive/10 text-destructive text-xs">
          <XCircle className="mr-1 h-3 w-3" />
          Erreur
        </Badge>
      );
    case "no_change":
      return (
        <Badge variant="outline" className="rounded-full text-xs">
          <MinusCircle className="mr-1 h-3 w-3" />
          Inchangé
        </Badge>
      );
    case "running":
      return (
        <Badge variant="outline" className="rounded-full border-blue-500 bg-blue-500/10 text-blue-700 text-xs">
          <Clock className="mr-1 h-3 w-3" />
          En cours
        </Badge>
      );
    default:
      return <Badge variant="outline" className="rounded-full text-xs">{status}</Badge>;
  }
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

export default function SyncsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [logs, setLogs] = useState<SyncLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [triggeringCdt, setTriggeringCdt] = useState(false);
  const [filter, setFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const fetchLogs = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "30" });
      if (filter) params.set("sync_type", filter);
      const data = await apiFetch<SyncLogsResponse>(
        `/admin/syncs/logs?${params}`,
        { token }
      );
      setLogs(data.logs);
      setTotal(data.total);
    } catch {
      toast.error("Erreur lors du chargement des logs");
    } finally {
      setLoading(false);
    }
  }, [token, page, filter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Auto-refresh logs every 10s
  useEffect(() => {
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, [fetchLogs]);

  const handleTriggerCodeTravail = async () => {
    if (!token) return;
    setTriggeringCdt(true);
    try {
      await apiFetch("/admin/syncs/code-travail", { method: "POST", token });
      toast.success("Synchronisation du Code du travail lancée");
      setTimeout(fetchLogs, 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("409")) {
        toast.warning("Une synchronisation est déjà en cours");
      } else {
        toast.error("Erreur lors du déclenchement");
      }
    } finally {
      setTriggeringCdt(false);
    }
  };

  const handleTrigger = async () => {
    if (!token) return;
    setTriggering(true);
    try {
      await apiFetch("/admin/syncs/trigger", { method: "POST", token });
      toast.success("Synchronisation planifiée lancée");
      // Refresh after a small delay to see the new log
      setTimeout(fetchLogs, 2000);
    } catch {
      toast.error("Erreur lors du déclenchement");
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Synchronisations
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Jurisprudence et conventions collectives — sync automatique le 1er et 15 de chaque mois à 3h.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTriggerCodeTravail}
            disabled={triggeringCdt}
          >
            <BookOpen className="mr-2 h-4 w-4" />
            {triggeringCdt ? "Synchronisation..." : "Code du travail"}
          </Button>
          <Button
            size="sm"
            onClick={handleTrigger}
            disabled={triggering}
          >
            <Play className="mr-2 h-4 w-4" />
            {triggering ? "Lancement..." : "Sync complète"}
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        <Button
          variant={filter === null ? "default" : "outline"}
          size="sm"
          onClick={() => { setFilter(null); setPage(1); }}
        >
          Tout
        </Button>
        <Button
          variant={filter === "jurisprudence" ? "default" : "outline"}
          size="sm"
          onClick={() => { setFilter("jurisprudence"); setPage(1); }}
        >
          Jurisprudence
        </Button>
        <Button
          variant={filter === "ccn" ? "default" : "outline"}
          size="sm"
          onClick={() => { setFilter("ccn"); setPage(1); }}
        >
          CCN
        </Button>
        <div className="flex-1" />
        <Button variant="ghost" size="sm" onClick={fetchLogs}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Rafraîchir
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Historique des synchronisations</CardTitle>
          <CardDescription>
            {total} entrée{total !== 1 ? "s" : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : logs.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              Aucune synchronisation enregistrée.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>IDCC</TableHead>
                  <TableHead>Statut</TableHead>
                  <TableHead className="text-right">Récupérés</TableHead>
                  <TableHead className="text-right">Créés</TableHead>
                  <TableHead className="text-right">Ignorés</TableHead>
                  <TableHead className="text-right">Erreurs</TableHead>
                  <TableHead>Durée</TableHead>
                  <TableHead>Détail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-sm whitespace-nowrap">
                      {new Date(log.started_at).toLocaleDateString("fr-FR", {
                        day: "2-digit",
                        month: "2-digit",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="rounded-full text-xs">
                        {log.sync_type === "jurisprudence" ? "Jurisprudence" : "CCN"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm font-mono">
                      {log.idcc ?? "—"}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={log.status} />
                    </TableCell>
                    <TableCell className="text-right text-sm">{log.items_fetched}</TableCell>
                    <TableCell className="text-right text-sm">{log.items_created}</TableCell>
                    <TableCell className="text-right text-sm">{log.items_skipped}</TableCell>
                    <TableCell className="text-right text-sm">
                      {log.errors > 0 ? (
                        <span className="text-destructive font-medium">{log.errors}</span>
                      ) : (
                        "0"
                      )}
                    </TableCell>
                    <TableCell className="text-sm whitespace-nowrap">
                      {formatDuration(log.duration_ms)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate" title={log.error_message ?? ""}>
                      {log.error_message ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}

          {/* Pagination */}
          {total > 30 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-sm text-muted-foreground">
                Page {page} / {Math.ceil(total / 30)}
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page === 1}
                  onClick={() => setPage(page - 1)}
                >
                  Précédent
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page * 30 >= total}
                  onClick={() => setPage(page + 1)}
                >
                  Suivant
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
