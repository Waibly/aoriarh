"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  FileUp,
  Loader2,
  RefreshCw,
  Replace,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch, authFetch } from "@/lib/api";
import type { Document } from "@/types/api";
import { SOURCE_TYPE_OPTIONS, NORME_POIDS } from "@/types/api";
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
  SelectGroup,
  SelectItem,
  SelectLabel,
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

const NIVEAU_LABELS: Record<number, string> = {
  1: "Constitution",
  2: "Normes internationales",
  3: "Lois & Ordonnances",
  4: "Jurisprudence",
  5: "Réglementaire",
  6: "Conventions collectives",
  7: "Usages & Engagements",
  8: "Règlement intérieur",
  9: "Contrat de travail",
};

const STATUS_CLASSES: Record<string, string> = {
  pending: "rounded-full",
  indexing: "rounded-full border-orange-400 bg-orange-500/10 text-orange-600 dark:text-orange-400",
  indexed: "rounded-full border-green-500 bg-green-500/10 text-green-600 dark:text-green-400",
  error: "rounded-full border-red-500 bg-red-500/10 text-red-600 dark:text-red-400",
};

const JURISPRUDENCE_SOURCE_TYPES = new Set([
  "arret_cour_cassation",
  "arret_conseil_etat",
  "decision_conseil_constitutionnel",
]);

const JURIDICTION_OPTIONS = ["Cour de cassation", "Conseil d'État", "Conseil constitutionnel"] as const;
const CHAMBRE_OPTIONS = ["Chambre sociale", "Chambre civile 1", "Chambre civile 2", "Chambre civile 3", "Chambre commerciale", "Chambre criminelle", "Assemblée plénière", "Chambre mixte"] as const;
const FORMATION_OPTIONS = ["Formation plénière de chambre", "Formation restreinte", "Section"] as const;
const SOLUTION_OPTIONS = ["Cassation", "Cassation partielle", "Rejet", "QPC", "Non-lieu à statuer"] as const;
const PUBLICATION_OPTIONS = ["Publié au Bulletin", "Inédit", "Mentionné aux tables"] as const;

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  indexing: "En cours",
  indexed: "Indexé",
  error: "Erreur",
};

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

interface DocumentGroup {
  source_type: string;
  label: string;
  count: number;
  indexed: number;
  pending: number;
  total_chunks: number;
}

interface DocumentGroupsResponse {
  groups: DocumentGroup[];
  total: number;
}

export default function DocumentsCommunsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [groups, setGroups] = useState<DocumentGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [syncingCdt, setSyncingCdt] = useState(false);
  const [reindexing, setReindexing] = useState(false);

  // Expanded groups with their loaded documents
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [groupDocs, setGroupDocs] = useState<Record<string, Document[]>>({});
  const [groupPages, setGroupPages] = useState<Record<string, number>>({});
  const [loadingGroup, setLoadingGroup] = useState<Record<string, boolean>>({});

  const fetchGroups = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<DocumentGroupsResponse>("/admin/documents/groups", { token });
      setGroups(data.groups);
    } catch {
      toast.error("Erreur lors du chargement");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  // Auto-refresh groups every 15s
  useEffect(() => {
    const interval = setInterval(fetchGroups, 15000);
    return () => clearInterval(interval);
  }, [fetchGroups]);

  const fetchGroupDocs = useCallback(async (sourceType: string, page: number = 1) => {
    if (!token) return;
    setLoadingGroup((prev) => ({ ...prev, [sourceType]: true }));
    try {
      const docs = await apiFetch<Document[]>(
        `/admin/documents/groups/${sourceType}?page=${page}&page_size=50`,
        { token },
      );
      setGroupDocs((prev) => ({ ...prev, [sourceType]: docs }));
      setGroupPages((prev) => ({ ...prev, [sourceType]: page }));
    } catch {
      toast.error("Erreur lors du chargement des documents");
    } finally {
      setLoadingGroup((prev) => ({ ...prev, [sourceType]: false }));
    }
  }, [token]);

  const toggleGroup = (sourceType: string) => {
    const isExpanded = expanded[sourceType];
    setExpanded((prev) => ({ ...prev, [sourceType]: !isExpanded }));
    if (!isExpanded && !groupDocs[sourceType]) {
      fetchGroupDocs(sourceType);
    }
  };

  const handleDelete = async (docId: string, sourceType: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/documents/${docId}`, { method: "DELETE", token });
      toast.success("Document supprimé");
      fetchGroups();
      fetchGroupDocs(sourceType, groupPages[sourceType] || 1);
    } catch {
      toast.error("Erreur lors de la suppression");
    }
  };

  const handleDownload = async (docId: string) => {
    if (!token) return;
    try {
      const res = await authFetch(`/admin/documents/${docId}/download`, { token });
      if (!res.ok) throw new Error("Erreur");
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition");
      let filename = "document";
      if (disposition) {
        const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
        if (utf8Match) {
          filename = decodeURIComponent(utf8Match[1].replace(/;.*$/, "").trim());
        } else {
          const asciiMatch = disposition.match(/filename="(.+?)"/);
          if (asciiMatch) filename = asciiMatch[1];
        }
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Erreur lors du téléchargement");
    }
  };

  const handleReindex = async (docId: string, sourceType: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/documents/${docId}/reindex`, { method: "POST", token });
      toast.success("Réindexation lancée");
      fetchGroupDocs(sourceType, groupPages[sourceType] || 1);
    } catch {
      toast.error("Erreur lors de la réindexation");
    }
  };

  const handleReplace = async (docId: string, file: File, sourceType: string) => {
    if (!token) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await authFetch(`/admin/documents/${docId}`, {
        method: "PUT",
        body: formData,
        token,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? "Erreur");
      }
      toast.success("Document remplacé — réindexation en cours");
      fetchGroupDocs(sourceType, groupPages[sourceType] || 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  };

  const handleReindexAll = async () => {
    if (!token) return;
    if (!confirm("Réindexer tous les documents ? Cette opération peut prendre plusieurs minutes.")) return;
    setReindexing(true);
    try {
      const res = await apiFetch("/admin/documents/actions/reindex-all", { method: "POST", token }) as { enqueued?: number };
      toast.success(`${res.enqueued ?? 0} documents en cours de réindexation`);
      fetchDocuments();
    } catch {
      toast.error("Erreur lors du lancement de la réindexation");
    } finally {
      setReindexing(false);
    }
  };

  const handleSyncCodeTravail = async () => {
    if (!token) return;
    setSyncingCdt(true);
    try {
      await apiFetch("/admin/syncs/code-travail", { method: "POST", token });
      toast.success("Synchronisation du Code du travail lancée");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      if (msg.includes("409")) {
        toast.warning("Une synchronisation est déjà en cours");
      } else {
        toast.error("Erreur lors de la synchronisation");
      }
    } finally {
      setSyncingCdt(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Documents communs</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleReindexAll} disabled={reindexing}>
            <RefreshCw className={`mr-2 h-4 w-4 ${reindexing ? "animate-spin" : ""}`} />
            {reindexing ? "Réindexation..." : "Réindexer tout"}
          </Button>
          <Button variant="outline" size="sm" onClick={handleSyncCodeTravail} disabled={syncingCdt}>
            <RefreshCw className={`mr-2 h-4 w-4 ${syncingCdt ? "animate-spin" : ""}`} />
            {syncingCdt ? "Sync..." : "Code du travail"}
          </Button>
          <Button size="sm" onClick={() => setUploadOpen(true)}>
            <FileUp className="mr-2 h-4 w-4" />
            Ajouter
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Base documentaire</CardTitle>
            <CardDescription>
              {groups.reduce((acc, g) => acc + g.count, 0)} documents communs — partagés avec toutes les organisations
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-1">
            {groups.map((group) => (
              <div key={group.source_type}>
                {/* Group header */}
                <button
                  onClick={() => toggleGroup(group.source_type)}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-muted/50 transition-colors"
                >
                  {expanded[group.source_type] ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-medium">{group.label}</span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {group.pending > 0 && (
                      <Badge variant="outline" className="rounded-full text-xs">
                        {group.pending} en attente
                      </Badge>
                    )}
                    <Badge variant="outline" className="rounded-full border-green-500 bg-green-500/10 text-green-600 text-xs">
                      {group.indexed} indexé{group.indexed > 1 ? "s" : ""}
                    </Badge>
                    <span className="text-xs text-muted-foreground w-20 text-right">
                      {group.total_chunks > 0 ? `${group.total_chunks.toLocaleString()} chunks` : "—"}
                    </span>
                    <span className="text-xs text-muted-foreground w-12 text-right font-mono">
                      {group.count}
                    </span>
                  </div>
                </button>

                {/* Expanded documents */}
                {expanded[group.source_type] && (
                  <div className="ml-7 border-l border-border pl-3 mb-2">
                    {loadingGroup[group.source_type] ? (
                      <div className="py-3 space-y-2">
                        {[1, 2, 3].map((i) => (
                          <Skeleton key={i} className="h-8 w-full" />
                        ))}
                      </div>
                    ) : (
                      <>
                        <div className="max-h-[60vh] overflow-y-auto">
                          <Table className="table-fixed">
                            <TableHeader>
                              <TableRow>
                                <TableHead className="w-[50%]">Nom</TableHead>
                                <TableHead className="w-[10%]">Statut</TableHead>
                                <TableHead className="w-[10%]">Taille</TableHead>
                                <TableHead className="w-[10%]">Date</TableHead>
                                <TableHead className="w-[20%] text-right">Actions</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {(groupDocs[group.source_type] ?? []).map((doc) => (
                                <GroupDocRow
                                  key={doc.id}
                                  doc={doc}
                                  sourceType={group.source_type}
                                  onDownload={handleDownload}
                                  onDelete={handleDelete}
                                  onReindex={handleReindex}
                                  onReplace={handleReplace}
                                />
                              ))}
                            </TableBody>
                          </Table>
                        </div>

                        {/* Numbered pagination */}
                        {group.count > 50 && (() => {
                          const currentPage = groupPages[group.source_type] || 1;
                          const totalPages = Math.ceil(group.count / 50);
                          const pages: (number | "...")[] = [];
                          for (let i = 1; i <= totalPages; i++) {
                            if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
                              pages.push(i);
                            } else if (pages[pages.length - 1] !== "...") {
                              pages.push("...");
                            }
                          }
                          return (
                            <div className="flex items-center justify-between pt-3 pb-1">
                              <p className="text-xs text-muted-foreground">
                                {(currentPage - 1) * 50 + 1}–{Math.min(currentPage * 50, group.count)} sur {group.count}
                              </p>
                              <div className="flex gap-1">
                                {pages.map((p, idx) =>
                                  p === "..." ? (
                                    <span key={`ellipsis-${idx}`} className="px-2 py-1 text-xs text-muted-foreground">…</span>
                                  ) : (
                                    <Button
                                      key={p}
                                      variant={p === currentPage ? "default" : "outline"}
                                      size="sm"
                                      className="h-7 w-7 p-0 text-xs"
                                      onClick={() => fetchGroupDocs(group.source_type, p)}
                                    >
                                      {p}
                                    </Button>
                                  )
                                )}
                              </div>
                            </div>
                          );
                        })()}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <CommonUploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        token={token}
        onUploaded={() => { fetchGroups(); }}
      />
    </div>
  );
}

/* ---- Document Row within a group ---- */

function GroupDocRow({
  doc,
  sourceType,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
}: {
  doc: Document;
  sourceType: string;
  onDownload: (id: string) => void;
  onDelete: (id: string, sourceType: string) => void;
  onReindex: (id: string, sourceType: string) => void;
  onReplace: (id: string, file: File, sourceType: string) => void;
}) {
  const replaceRef = useRef<HTMLInputElement>(null);

  return (
    <TableRow>
      <TableCell className="text-sm">
        <span className="line-clamp-2">{doc.name}</span>
      </TableCell>
      <TableCell>
        <Badge variant="outline" className={STATUS_CLASSES[doc.indexation_status] ?? "rounded-full"}>
          {doc.indexation_status === "indexing" && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
          {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
        </Badge>
      </TableCell>
      <TableCell className="text-sm">{formatFileSize(doc.file_size)}</TableCell>
      <TableCell className="text-sm">
        {new Date(doc.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onDownload(doc.id)} title="Télécharger">
            <Download className="h-3.5 w-3.5" />
          </Button>
          <input
            ref={replaceRef}
            type="file"
            accept=".pdf,.docx,.txt"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onReplace(doc.id, f, sourceType);
              e.target.value = "";
            }}
          />
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => replaceRef.current?.click()} title="Remplacer">
            <Replace className="h-3.5 w-3.5 text-blue-500" />
          </Button>
          {doc.indexation_status === "error" && (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onReindex(doc.id, sourceType)} title="Réindexer">
              <RefreshCw className="h-3.5 w-3.5 text-orange-500" />
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onDelete(doc.id, sourceType)} title="Supprimer">
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/* ---- Upload Dialog ---- */

interface CommonUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token?: string;
  onUploaded: () => void;
}

function CommonUploadDialog({
  open,
  onOpenChange,
  token,
  onUploaded,
}: CommonUploadDialogProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [sourceType, setSourceType] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Jurisprudence metadata
  const [juridiction, setJuridiction] = useState("");
  const [chambre, setChambre] = useState("");
  const [formation, setFormation] = useState("");
  const [numeroPourvoi, setNumeroPourvoi] = useState("");
  const [dateDecision, setDateDecision] = useState("");
  const [solution, setSolution] = useState("");
  const [publication, setPublication] = useState("");

  const isJurisprudence = JURISPRUDENCE_SOURCE_TYPES.has(sourceType);
  const isBatch = files.length > 1;

  const selectedOption = SOURCE_TYPE_OPTIONS.find((s) => s.value === sourceType);
  const niveau = selectedOption?.niveau;
  const poids = niveau ? NORME_POIDS[niveau] : null;

  useEffect(() => {
    if (open) {
      setFiles([]);
      setSourceType("");
      setError(null);
      setJuridiction("");
      setChambre("");
      setFormation("");
      setNumeroPourvoi("");
      setDateDecision("");
      setSolution("");
      setPublication("");
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0 || !sourceType) return;

    setSubmitting(true);
    setError(null);

    try {
      if (isBatch) {
        const formData = new FormData();
        for (const f of files) formData.append("files", f);
        formData.append("source_type", sourceType);

        const res = await authFetch(`/admin/documents/batch`, {
          method: "POST",
          body: formData,
          token: token ?? undefined,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail ?? "Erreur lors de l'upload");
        }

        const data = await res.json();
        if (data.failed > 0) {
          const failedNames = data.results
            .filter((r: { success: boolean }) => !r.success)
            .map((r: { filename: string; error: string }) => `${r.filename}: ${r.error}`)
            .join("\n");
          toast.warning(
            `${data.succeeded} ajouté${data.succeeded > 1 ? "s" : ""}, ${data.failed} échoué${data.failed > 1 ? "s" : ""}`,
            { description: failedNames, duration: 8000 }
          );
        } else {
          toast.success(`${data.succeeded} document${data.succeeded > 1 ? "s" : ""} ajouté${data.succeeded > 1 ? "s" : ""}`);
        }
      } else {
        const formData = new FormData();
        formData.append("file", files[0]);
        formData.append("source_type", sourceType);
        if (isJurisprudence) {
          if (juridiction) formData.append("juridiction", juridiction);
          if (chambre) formData.append("chambre", chambre);
          if (formation) formData.append("formation", formation);
          if (numeroPourvoi) formData.append("numero_pourvoi", numeroPourvoi);
          if (dateDecision) formData.append("date_decision", dateDecision);
          if (solution) formData.append("solution", solution);
          if (publication) formData.append("publication", publication);
        }

        const res = await authFetch(`/admin/documents/`, {
          method: "POST",
          body: formData,
          token: token ?? undefined,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail ?? "Erreur lors de l'upload");
        }

        toast.success("Document commun ajouté");
      }

      onOpenChange(false);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de l'upload");
    } finally {
      setSubmitting(false);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // Group options by niveau
  const grouped = new Map<number, typeof SOURCE_TYPE_OPTIONS>();
  for (const opt of SOURCE_TYPE_OPTIONS) {
    const group = grouped.get(opt.niveau) ?? [];
    group.push(opt);
    grouped.set(opt.niveau, group);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Ajouter des documents communs</DialogTitle>
          <DialogDescription>
            Sélectionnez un ou plusieurs fichiers du même type. Formats
            acceptés : PDF, Word (.docx), Texte (.txt)
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="common-doc-file">
              Fichier{files.length > 1 ? "s" : ""} *
              {files.length > 0 && (
                <span className="text-muted-foreground ml-1">
                  ({files.length} sélectionné{files.length > 1 ? "s" : ""})
                </span>
              )}
            </Label>
            <input
              ref={fileRef}
              id="common-doc-file"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
              required={files.length === 0}
            />
            {files.length > 1 && (
              <div className="max-h-32 overflow-y-auto rounded-md border p-2 space-y-1">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="truncate mr-2">{f.name}</span>
                    <button type="button" onClick={() => removeFile(i)} className="text-destructive hover:underline shrink-0">
                      Retirer
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="common-source-type">Type de document *</Label>
            <Select value={sourceType} onValueChange={setSourceType}>
              <SelectTrigger id="common-source-type">
                <SelectValue placeholder="Sélectionner le type..." />
              </SelectTrigger>
              <SelectContent>
                {Array.from(grouped.entries()).map(([niv, options]) => (
                  <SelectGroup key={niv}>
                    <SelectLabel>
                      Niveau {niv} — {NIVEAU_LABELS[niv]}
                    </SelectLabel>
                    {options.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>

          {niveau && (
            <div className="flex gap-6 rounded-md border p-3 text-sm">
              <div>
                <span className="text-muted-foreground">Niveau : </span>
                <span className="font-medium">{niveau} — {NIVEAU_LABELS[niveau]}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Poids : </span>
                <span className="font-medium">{poids}</span>
              </div>
            </div>
          )}

          {isJurisprudence && !isBatch && (
            <div className="space-y-3 rounded-md border border-border bg-muted/50 p-4">
              <p className="text-sm font-medium">Métadonnées jurisprudence</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="c-juridiction" className="text-xs">Juridiction</Label>
                  <Select value={juridiction} onValueChange={setJuridiction}>
                    <SelectTrigger id="c-juridiction"><SelectValue placeholder="Sélectionner..." /></SelectTrigger>
                    <SelectContent>{JURIDICTION_OPTIONS.map((j) => <SelectItem key={j} value={j}>{j}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="c-chambre" className="text-xs">Chambre</Label>
                  <Select value={chambre} onValueChange={setChambre}>
                    <SelectTrigger id="c-chambre"><SelectValue placeholder="Sélectionner..." /></SelectTrigger>
                    <SelectContent>{CHAMBRE_OPTIONS.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="c-formation" className="text-xs">Formation</Label>
                  <Select value={formation} onValueChange={setFormation}>
                    <SelectTrigger id="c-formation"><SelectValue placeholder="Sélectionner..." /></SelectTrigger>
                    <SelectContent>{FORMATION_OPTIONS.map((f) => <SelectItem key={f} value={f}>{f}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="c-numero-pourvoi" className="text-xs">N° de pourvoi</Label>
                  <Input id="c-numero-pourvoi" placeholder="ex: 21-14.490" value={numeroPourvoi} onChange={(e) => setNumeroPourvoi(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="c-date-decision" className="text-xs">Date de décision</Label>
                  <Input id="c-date-decision" type="date" value={dateDecision} onChange={(e) => setDateDecision(e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="c-solution" className="text-xs">Solution</Label>
                  <Select value={solution} onValueChange={setSolution}>
                    <SelectTrigger id="c-solution"><SelectValue placeholder="Sélectionner..." /></SelectTrigger>
                    <SelectContent>{SOLUTION_OPTIONS.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="col-span-2 space-y-1">
                  <Label htmlFor="c-publication" className="text-xs">Publication</Label>
                  <Select value={publication} onValueChange={setPublication}>
                    <SelectTrigger id="c-publication"><SelectValue placeholder="Sélectionner..." /></SelectTrigger>
                    <SelectContent>{PUBLICATION_OPTIONS.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          {isBatch && isJurisprudence && (
            <p className="text-xs text-muted-foreground">
              Les métadonnées de jurisprudence ne sont pas disponibles en upload par lot.
            </p>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button type="submit" disabled={submitting || files.length === 0 || !sourceType}>
              {submitting ? "Upload en cours..." : files.length > 1 ? `Ajouter ${files.length} documents` : "Ajouter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
