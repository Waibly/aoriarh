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
  const [running, setRunning] = useState<string | null>(null);

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

  const triggerSync = async (key: string) => {
    setRunning(key);
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
      toast.success("Sync lancée");
      onRefresh();
      setTimeout(loadLastSyncs, 1000);
    } catch {
      toast.error("Échec de la sync");
    } finally {
      setRunning(null);
    }
  };

  const sources = [
    { key: "kali", label: "KALI (CCN)" },
    { key: "judilibre", label: "Judilibre" },
    { key: "code_travail", label: "Code travail" },
    { key: "bocc", label: "BOCC" },
  ];

  return (
    <Card>
      <CardContent className="p-3 grid grid-cols-2 md:grid-cols-4 gap-2">
        {sources.map((s) => {
          const log = lastSyncs[s.key];
          const ok = log
            ? ["ok", "success", "completed"].includes(log.status.toLowerCase())
            : false;
          return (
            <div
              key={s.key}
              className="flex items-center justify-between gap-2 border rounded-md p-2 text-xs"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                  {loading ? (
                    <Skeleton className="h-3 w-3" />
                  ) : log ? (
                    ok ? (
                      <CheckCircle2 className="h-3 w-3 text-green-600" />
                    ) : (
                      <AlertCircle className="h-3 w-3 text-red-600" />
                    )
                  ) : (
                    <span className="h-3 w-3 inline-block rounded-full bg-muted-foreground/30" />
                  )}
                  <span className="font-medium truncate">{s.label}</span>
                </div>
                <div className="text-muted-foreground text-[10px] truncate">
                  {log ? fmtRelative(log.started_at) : "—"}
                </div>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={running === s.key}
                onClick={() => triggerSync(s.key)}
                className="h-7 px-2 text-[11px]"
              >
                {running === s.key ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
              </Button>
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
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setTestOpen(true)}>
            <FlaskConical className="h-4 w-4 mr-2" />
            Tester recherche
          </Button>
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
            <CardContent className="p-0">
              {docsLoading ? (
                <div className="p-4 space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : filteredDocs.length === 0 ? (
                <div className="p-12 text-center text-sm text-muted-foreground">
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
