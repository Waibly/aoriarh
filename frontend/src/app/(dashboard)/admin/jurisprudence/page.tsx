"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  BookOpen,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  RefreshCw,
  Scale,
} from "lucide-react";
import { toast } from "sonner";
import { authFetch } from "@/lib/api";
import type { Document } from "@/types/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

interface JurisprudenceStats {
  total: number;
  indexed: number;
  pending: number;
  indexing: number;
  errors: number;
  oldest_decision: string | null;
  newest_decision: string | null;
  last_sync: string | null;
}

interface SyncResponse {
  status: string;
  message: string;
}

const STATUS_CLASSES: Record<string, string> = {
  pending: "rounded-full",
  indexing: "rounded-full border-orange-400 bg-orange-500/10 text-orange-600 dark:text-orange-400",
  indexed: "rounded-full border-green-500 bg-green-500/10 text-green-600 dark:text-green-400",
  error: "rounded-full border-red-500 bg-red-500/10 text-red-600 dark:text-red-400",
};

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  indexing: "Indexation...",
  indexed: "Indexé",
  error: "Erreur",
};

const CHAMBER_OPTIONS = [
  { value: "soc", label: "Chambre sociale" },
  { value: "civ1", label: "Chambre civile 1" },
  { value: "civ2", label: "Chambre civile 2" },
  { value: "civ3", label: "Chambre civile 3" },
  { value: "com", label: "Chambre commerciale" },
  { value: "crim", label: "Chambre criminelle" },
] as const;

const PUBLICATION_OPTIONS = [
  { value: "b", label: "Publié au Bulletin" },
  { value: "r", label: "Mentionné aux tables" },
  { value: "c", label: "Inédit" },
] as const;

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export default function JurisprudencePage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const PAGE_SIZE = 50;
  const [stats, setStats] = useState<JurisprudenceStats | null>(null);
  const [decisions, setDecisions] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [page, setPage] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, decisionsRes] = await Promise.all([
        authFetch("/admin/jurisprudence/stats", { token }),
        authFetch(`/admin/jurisprudence/decisions?page=${page}&page_size=${PAGE_SIZE}`, { token }),
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (decisionsRes.ok) setDecisions(await decisionsRes.json());
    } catch {
      toast.error("Erreur lors du chargement");
    } finally {
      setLoading(false);
    }
  }, [token, page]);

  useEffect(() => {
    if (token) fetchData();
  }, [token, fetchData]);

  // Poll for indexation progress
  useEffect(() => {
    const hasActive = decisions.some(
      (d) => d.indexation_status === "pending" || d.indexation_status === "indexing"
    );
    if (!hasActive) return;

    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [decisions, fetchData]);

  if (loading && !stats) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Scale className="h-6 w-6" />
            Jurisprudence
          </h1>
          <p className="text-muted-foreground">
            Synchronisation des arrêts depuis l&apos;API Judilibre (Cour de cassation)
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Actualiser
          </Button>
          <Button size="sm" onClick={() => setSyncDialogOpen(true)}>
            <Download className="mr-2 h-4 w-4" />
            Synchroniser
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Arrêts ingérés</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.total}</div>
              <p className="text-xs text-muted-foreground">
                {stats.indexed} indexés
                {stats.pending + stats.indexing > 0 &&
                  ` · ${stats.pending + stats.indexing} en cours`}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Décision la plus récente</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">
                {formatDate(stats.newest_decision)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Décision la plus ancienne</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">
                {formatDate(stats.oldest_decision)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Dernière synchronisation</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-semibold">
                {formatDate(stats.last_sync)}
              </div>
              {stats.errors > 0 && (
                <p className="text-xs text-destructive">
                  {stats.errors} erreur{stats.errors > 1 ? "s" : ""}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Decisions table */}
      <Card>
        <CardHeader>
          <CardTitle>Arrêts ingérés</CardTitle>
          <CardDescription>
            Décisions de la Cour de cassation importées depuis Judilibre
          </CardDescription>
        </CardHeader>
        <CardContent>
          {decisions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <BookOpen className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm">Aucun arrêt importé</p>
              <p className="text-xs mt-1">
                Lancez une synchronisation pour importer des arrêts depuis Judilibre
              </p>
            </div>
          ) : (
            <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>N° pourvoi</TableHead>
                  <TableHead>Chambre</TableHead>
                  <TableHead>Solution</TableHead>
                  <TableHead>Publication</TableHead>
                  <TableHead>Statut</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {decisions.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="text-sm">
                      {formatDate(doc.date_decision)}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {doc.numero_pourvoi || "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      {doc.chambre || "—"}
                    </TableCell>
                    <TableCell className="text-sm">
                      {doc.solution || "—"}
                    </TableCell>
                    <TableCell>
                      {doc.publication && (
                        <Badge variant="outline" className="rounded-full text-xs">
                          {doc.publication}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className={STATUS_CLASSES[doc.indexation_status] ?? "rounded-full"}>
                          {doc.indexation_status === "indexing" && (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          )}
                          {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
                        </Badge>
                        {doc.indexation_status === "indexing" && doc.indexation_progress != null && (
                          <span className="text-xs text-muted-foreground">
                            {doc.indexation_progress}%
                          </span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {/* Pagination */}
            {stats && stats.total > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t pt-4">
                <p className="text-sm text-muted-foreground">
                  {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, stats.total)} sur {stats.total} arrêts
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft className="mr-1 h-4 w-4" />
                    Précédent
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={(page + 1) * PAGE_SIZE >= stats.total}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Suivant
                    <ChevronRight className="ml-1 h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Sync dialog */}
      <SyncDialog
        open={syncDialogOpen}
        onOpenChange={setSyncDialogOpen}
        token={token}
        onComplete={() => {
          fetchData();
        }}
      />
    </div>
  );
}

/* ---- Sync Dialog ---- */

interface SyncDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token?: string;
  onComplete: () => void;
}

function SyncDialog({ open, onOpenChange, token, onComplete }: SyncDialogProps) {
  const [chamber, setChamber] = useState("soc");
  const [publication, setPublication] = useState("b");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [maxDecisions, setMaxDecisions] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<SyncResponse | null>(null);

  useEffect(() => {
    if (open) {
      setResult(null);
      setSyncing(false);
      // Default: 3 years back
      const now = new Date();
      const threeYearsAgo = new Date(now.getFullYear() - 3, now.getMonth(), now.getDate());
      setDateStart(threeYearsAgo.toISOString().split("T")[0]);
      setDateEnd(now.toISOString().split("T")[0]);
      setMaxDecisions("");
    }
  }, [open]);

  const handleSync = async () => {
    setSyncing(true);
    setResult(null);

    try {
      const body: Record<string, unknown> = {
        chamber,
        publication,
      };
      if (dateStart) body.date_start = dateStart;
      if (dateEnd) body.date_end = dateEnd;
      if (maxDecisions) body.max_decisions = parseInt(maxDecisions, 10);

      const res = await authFetch("/admin/jurisprudence/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        token,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? "Erreur lors de la synchronisation");
      }

      const data: SyncResponse = await res.json();
      setResult(data);
      toast.success(data.message);
      onComplete();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors de la synchronisation"
      );
    } finally {
      setSyncing(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Synchroniser Judilibre</DialogTitle>
          <DialogDescription>
            Importer des arrêts depuis l&apos;API Judilibre de la Cour de cassation.
            Les arrêts déjà importés seront ignorés.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Chambre</Label>
              <Select value={chamber} onValueChange={setChamber}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CHAMBER_OPTIONS.map((c) => (
                    <SelectItem key={c.value} value={c.value}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Publication</Label>
              <Select value={publication} onValueChange={setPublication}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PUBLICATION_OPTIONS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Date début</Label>
              <Input
                type="date"
                value={dateStart}
                onChange={(e) => setDateStart(e.target.value)}
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Date fin</Label>
              <Input
                type="date"
                value={dateEnd}
                onChange={(e) => setDateEnd(e.target.value)}
              />
            </div>

            <div className="col-span-2 space-y-1">
              <Label className="text-xs">
                Nombre maximum d&apos;arrêts{" "}
                <span className="text-muted-foreground">(optionnel)</span>
              </Label>
              <Input
                type="number"
                placeholder="Tous"
                min={1}
                value={maxDecisions}
                onChange={(e) => setMaxDecisions(e.target.value)}
              />
            </div>
          </div>

          {/* Result display */}
          {result && (
            <div className="rounded-md border p-4 space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500" />
                <span className="font-medium">Synchronisation lancée</span>
              </div>
              <p className="text-muted-foreground">{result.message}</p>
            </div>
          )}
        </div>

        <DialogFooter>
          {result ? (
            <Button onClick={() => onOpenChange(false)}>Fermer</Button>
          ) : (
            <Button onClick={handleSync} disabled={syncing}>
              {syncing ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Synchronisation...
                </>
              ) : (
                <>
                  <Download className="mr-2 h-4 w-4" />
                  Lancer la synchronisation
                </>
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
