"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { Download, FileUp, Loader2, RefreshCw, Replace, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { cn } from "@/lib/utils";

// API_BASE_URL importé via authFetch — plus de fetch direct

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

const STATUS_VARIANT: Record<string, "secondary" | "outline" | "destructive" | "default"> = {
  pending: "outline",
  indexing: "outline",
  indexed: "secondary",
  error: "destructive",
};

const JURISPRUDENCE_SOURCE_TYPES = new Set([
  "arret_cour_cassation",
  "arret_conseil_etat",
  "decision_conseil_constitutionnel",
]);

const JURIDICTION_OPTIONS = [
  "Cour de cassation",
  "Conseil d'État",
  "Conseil constitutionnel",
] as const;

const CHAMBRE_OPTIONS = [
  "Chambre sociale",
  "Chambre civile 1",
  "Chambre civile 2",
  "Chambre civile 3",
  "Chambre commerciale",
  "Chambre criminelle",
  "Assemblée plénière",
  "Chambre mixte",
] as const;

const FORMATION_OPTIONS = [
  "Formation plénière de chambre",
  "Formation restreinte",
  "Section",
] as const;

const SOLUTION_OPTIONS = [
  "Cassation",
  "Cassation partielle",
  "Rejet",
  "QPC",
  "Non-lieu à statuer",
] as const;

const PUBLICATION_OPTIONS = [
  "Publié au Bulletin",
  "Inédit",
  "Mentionné aux tables",
] as const;

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

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function DocumentsPage() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const token = session?.access_token;

  const [documents, setDocuments] = useState<Document[]>([]);
  const [commonDocs, setCommonDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingCommon, setLoadingCommon] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [isManager, setIsManager] = useState(false);
  const [dragging, setDragging] = useState(false);

  const initialLoadDone = useRef(false);

  const fetchDocuments = useCallback(async () => {
    if (!currentOrg || !token) return;
    if (!initialLoadDone.current) setLoading(true);
    try {
      const docs = await apiFetch<Document[]>(
        `/documents/${currentOrg.id}/`,
        { token }
      );
      setDocuments(docs);
      initialLoadDone.current = true;
    } catch {
      toast.error("Erreur lors du chargement des documents");
    } finally {
      setLoading(false);
    }
  }, [currentOrg, token]);

  const initialCommonLoadDone = useRef(false);

  const fetchCommonDocs = useCallback(async () => {
    if (!token) return;
    if (!initialCommonLoadDone.current) setLoadingCommon(true);
    try {
      const docs = await apiFetch<Document[]>("/documents/common/", { token });
      setCommonDocs(docs);
      initialCommonLoadDone.current = true;
    } catch {
      toast.error("Erreur lors du chargement des documents communs");
    } finally {
      setLoadingCommon(false);
    }
  }, [token]);

  useEffect(() => {
    initialLoadDone.current = false;
    fetchDocuments();
  }, [fetchDocuments]);

  useEffect(() => {
    initialCommonLoadDone.current = false;
    fetchCommonDocs();
  }, [fetchCommonDocs]);

  // Polling : rafraîchir tant qu'un document est en cours de traitement
  useEffect(() => {
    const hasPending = documents.some(
      (d) => d.indexation_status === "pending" || d.indexation_status === "indexing"
    );
    if (!hasPending) return;
    const interval = setInterval(() => {
      fetchDocuments();
    }, 5000);
    return () => clearInterval(interval);
  }, [documents, fetchDocuments]);

  useEffect(() => {
    setIsManager(
      session?.user?.role === "admin" || session?.user?.role === "manager"
    );
  }, [session]);

  const handleDelete = async (docId: string) => {
    if (!currentOrg || !token) return;
    try {
      await apiFetch(`/documents/${currentOrg.id}/${docId}`, {
        method: "DELETE",
        token,
      });
      toast.success("Document supprimé");
      fetchDocuments();
    } catch {
      toast.error("Erreur lors de la suppression");
    }
  };

  const handleDownload = async (docId: string) => {
    if (!currentOrg || !token) return;
    try {
      const { url } = await apiFetch<{ url: string }>(
        `/documents/${currentOrg.id}/${docId}/download`,
        { token }
      );
      window.open(url, "_blank");
    } catch {
      toast.error("Erreur lors du téléchargement");
    }
  };

  const handleReindex = async (docId: string) => {
    if (!currentOrg || !token) return;
    try {
      await apiFetch(`/documents/${currentOrg.id}/${docId}/reindex`, {
        method: "POST",
        token,
      });
      toast.success("Réindexation lancée");
      fetchDocuments();
    } catch {
      toast.error("Erreur lors de la réindexation");
    }
  };

  const handleReplace = async (docId: string, file: File) => {
    if (!currentOrg || !token) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await authFetch(`/documents/${currentOrg.id}/${docId}`, {
        method: "PUT",
        body: formData,
        token,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? "Erreur lors du remplacement");
      }
      toast.success("Document remplacé — réindexation en cours");
      fetchDocuments();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors du remplacement"
      );
    }
  };

  /* ---- Drag & Drop ---- */

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    const droppedFile = e.dataTransfer.files?.[0];
    if (droppedFile) {
      setUploadOpen(true);
      // Small delay to let the dialog mount before setting the file
      setTimeout(() => {
        window.dispatchEvent(
          new CustomEvent("dropped-file", { detail: droppedFile })
        );
      }, 100);
    }
  };

  if (!currentOrg) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="text-muted-foreground">
          Aucune organisation sélectionnée. Créez ou rejoignez une organisation.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>

      {/* Drop zone */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "flex flex-col items-center justify-center rounded-lg border-2 border-dashed bg-white p-8 transition-colors dark:bg-card",
          dragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25"
        )}
      >
        <Upload className="mb-2 h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          Glissez-déposez un fichier ici ou{" "}
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            parcourez vos fichiers
          </button>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          PDF, Word (.docx), Texte (.txt)
        </p>
      </div>

      <Tabs defaultValue="org">
        <TabsList>
          <TabsTrigger value="org">
            Documents de {currentOrg.name}
          </TabsTrigger>
          <TabsTrigger value="common">Documents communs</TabsTrigger>
        </TabsList>

        {/* ---- Org documents tab ---- */}
        <TabsContent value="org">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div className="space-y-1.5">
                <CardTitle>Documents de {currentOrg.name}</CardTitle>
                <CardDescription>
                  {documents.length} document
                  {documents.length !== 1 ? "s" : ""}
                </CardDescription>
              </div>
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                <FileUp className="mr-2 h-4 w-4" />
                Ajouter un document
              </Button>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : documents.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Aucun document. Ajoutez votre premier document juridique.
                </p>
              ) : (
                <DocumentTable
                  documents={documents}
                  isManager={isManager}
                  onDownload={handleDownload}
                  onDelete={handleDelete}
                  onReindex={handleReindex}
                  onReplace={handleReplace}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---- Common documents tab ---- */}
        <TabsContent value="common">
          <Card>
            <CardHeader>
              <div className="space-y-1.5">
                <CardTitle>Documents communs</CardTitle>
                <CardDescription>
                  {commonDocs.length} document
                  {commonDocs.length !== 1 ? "s" : ""} — partagés avec toutes
                  les organisations
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {loadingCommon ? (
                <div className="space-y-3">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-12 w-full" />
                  ))}
                </div>
              ) : commonDocs.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Aucun document commun disponible.
                </p>
              ) : (
                <CommonDocTable documents={commonDocs} />
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        orgId={currentOrg.id}
        token={token}
        onUploaded={fetchDocuments}
      />
    </div>
  );
}

/* ---- Shared Document Table ---- */

function DocumentTable({
  documents,
  isManager,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
}: {
  documents: Document[];
  isManager: boolean;
  onDownload: (id: string) => void;
  onDelete: (id: string) => void;
  onReindex: (id: string) => void;
  onReplace: (id: string, file: File) => void;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Nom</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Niveau</TableHead>
          <TableHead>Statut</TableHead>
          <TableHead>Indexation</TableHead>
          <TableHead>Format</TableHead>
          <TableHead>Taille</TableHead>
          <TableHead>Date</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((doc) => (
          <DocumentRow
            key={doc.id}
            doc={doc}
            isManager={isManager}
            onDownload={onDownload}
            onDelete={onDelete}
            onReindex={onReindex}
            onReplace={onReplace}
          />
        ))}
      </TableBody>
    </Table>
  );
}

function DocumentRow({
  doc,
  isManager,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
}: {
  doc: Document;
  isManager: boolean;
  onDownload: (id: string) => void;
  onDelete: (id: string) => void;
  onReindex: (id: string) => void;
  onReplace: (id: string, file: File) => void;
}) {
  const replaceRef = useRef<HTMLInputElement>(null);
  const sourceLabel =
    SOURCE_TYPE_OPTIONS.find((s) => s.value === doc.source_type)?.label ??
    doc.source_type;

  return (
    <TableRow>
      <TableCell className="max-w-[200px] truncate font-medium">
        {doc.name}
      </TableCell>
      <TableCell className="text-sm">{sourceLabel}</TableCell>
      <TableCell className="text-sm">
        {doc.norme_niveau ? `N${doc.norme_niveau}` : "—"}
      </TableCell>
      <TableCell>
        <Badge
          variant={STATUS_VARIANT[doc.indexation_status] ?? "outline"}
          className={doc.indexation_status === "indexing" ? "border-orange-400 text-orange-600 dark:text-orange-400" : undefined}
        >
          {doc.indexation_status === "indexing" && (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          )}
          {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
        </Badge>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {doc.indexation_status === "indexing" ? (
          <span className="flex items-center gap-1 text-orange-600 dark:text-orange-400">
            <Loader2 className="h-3 w-3 animate-spin" />
            {doc.indexation_progress != null ? `${doc.indexation_progress}%` : "En cours"}
          </span>
        ) : doc.indexation_status === "error" && doc.indexation_error ? (
          <span className="text-destructive" title={doc.indexation_error}>
            Échoué
          </span>
        ) : (
          formatDuration(doc.indexation_duration_ms)
        )}
      </TableCell>
      <TableCell className="text-sm uppercase">
        {doc.file_format ?? "—"}
      </TableCell>
      <TableCell className="text-sm">{formatFileSize(doc.file_size)}</TableCell>
      <TableCell className="text-sm">
        {new Date(doc.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDownload(doc.id)}
            title="Télécharger"
          >
            <Download className="h-4 w-4" />
          </Button>
          {isManager && (
            <>
              <input
                ref={replaceRef}
                type="file"
                accept=".pdf,.docx,.txt"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onReplace(doc.id, f);
                  e.target.value = "";
                }}
              />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => replaceRef.current?.click()}
                title="Remplacer le fichier"
              >
                <Replace className="h-4 w-4 text-blue-500" />
              </Button>
            </>
          )}
          {doc.indexation_status === "error" && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onReindex(doc.id)}
              title="Réindexer"
            >
              <RefreshCw className="h-4 w-4 text-orange-500" />
            </Button>
          )}
          {isManager && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDelete(doc.id)}
              title="Supprimer"
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

/* ---- Common Documents Table (read-only) ---- */

function CommonDocTable({ documents }: { documents: Document[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Nom</TableHead>
          <TableHead>Type</TableHead>
          <TableHead>Niveau</TableHead>
          <TableHead>Statut</TableHead>
          <TableHead>Indexation</TableHead>
          <TableHead>Format</TableHead>
          <TableHead>Taille</TableHead>
          <TableHead>Date</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((doc) => {
          const sourceLabel =
            SOURCE_TYPE_OPTIONS.find((s) => s.value === doc.source_type)
              ?.label ?? doc.source_type;
          return (
            <TableRow key={doc.id}>
              <TableCell className="max-w-[200px] truncate font-medium">
                {doc.name}
              </TableCell>
              <TableCell className="text-sm">{sourceLabel}</TableCell>
              <TableCell className="text-sm">
                {doc.norme_niveau ? `N${doc.norme_niveau}` : "—"}
              </TableCell>
              <TableCell>
                <Badge
                  variant={
                    STATUS_VARIANT[doc.indexation_status] ?? "outline"
                  }
                  className={doc.indexation_status === "indexing" ? "border-orange-400 text-orange-600 dark:text-orange-400" : undefined}
                >
                  {doc.indexation_status === "indexing" && (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  )}
                  {STATUS_LABEL[doc.indexation_status] ??
                    doc.indexation_status}
                </Badge>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {doc.indexation_status === "indexing" ? (
                  <span className="flex items-center gap-1 text-orange-600 dark:text-orange-400">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {doc.indexation_progress != null ? `${doc.indexation_progress}%` : "En cours"}
                  </span>
                ) : doc.indexation_status === "error" && doc.indexation_error ? (
                  <span className="text-destructive" title={doc.indexation_error}>
                    Échoué
                  </span>
                ) : (
                  formatDuration(doc.indexation_duration_ms)
                )}
              </TableCell>
              <TableCell className="text-sm uppercase">
                {doc.file_format ?? "—"}
              </TableCell>
              <TableCell className="text-sm">
                {formatFileSize(doc.file_size)}
              </TableCell>
              <TableCell className="text-sm">
                {new Date(doc.created_at).toLocaleDateString("fr-FR")}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/* ---- Upload Dialog ---- */

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  token?: string;
  onUploaded: () => void;
}

function UploadDialog({
  open,
  onOpenChange,
  orgId,
  token,
  onUploaded,
}: UploadDialogProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
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

  const selectedOption = SOURCE_TYPE_OPTIONS.find(
    (s) => s.value === sourceType
  );
  const niveau = selectedOption?.niveau;
  const poids = niveau ? NORME_POIDS[niveau] : null;

  useEffect(() => {
    if (open) {
      setFile(null);
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

  // Listen for dropped file from drag & drop zone
  useEffect(() => {
    const handler = (e: Event) => {
      const droppedFile = (e as CustomEvent<File>).detail;
      if (droppedFile) setFile(droppedFile);
    };
    window.addEventListener("dropped-file", handler);
    return () => window.removeEventListener("dropped-file", handler);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !sourceType) return;

    setSubmitting(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);
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

    try {
      const res = await authFetch(`/documents/${orgId}/`, {
        method: "POST",
        body: formData,
        token: token ?? undefined,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail ?? "Erreur lors de l'upload");
      }

      toast.success("Document ajouté");
      onOpenChange(false);
      onUploaded();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Erreur lors de l'upload"
      );
    } finally {
      setSubmitting(false);
    }
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
          <DialogTitle>Ajouter un document</DialogTitle>
          <DialogDescription>
            Formats acceptés : PDF, Word (.docx), Texte (.txt)
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="doc-file">
              Fichier * {file && <span className="text-muted-foreground">({file.name})</span>}
            </Label>
            <input
              ref={fileRef}
              id="doc-file"
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
              required={!file}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="source-type">Type de document *</Label>
            <Select value={sourceType} onValueChange={setSourceType}>
              <SelectTrigger id="source-type">
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
                <span className="font-medium">
                  {niveau} — {NIVEAU_LABELS[niveau]}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Poids : </span>
                <span className="font-medium">{poids}</span>
              </div>
            </div>
          )}

          {isJurisprudence && (
            <div className="space-y-3 rounded-md border border-border bg-muted/50 p-4">
              <p className="text-sm font-medium">Métadonnées jurisprudence</p>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="juridiction" className="text-xs">Juridiction</Label>
                  <Select value={juridiction} onValueChange={setJuridiction}>
                    <SelectTrigger id="juridiction">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {JURIDICTION_OPTIONS.map((j) => (
                        <SelectItem key={j} value={j}>{j}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="chambre" className="text-xs">Chambre</Label>
                  <Select value={chambre} onValueChange={setChambre}>
                    <SelectTrigger id="chambre">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {CHAMBRE_OPTIONS.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="formation" className="text-xs">Formation</Label>
                  <Select value={formation} onValueChange={setFormation}>
                    <SelectTrigger id="formation">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {FORMATION_OPTIONS.map((f) => (
                        <SelectItem key={f} value={f}>{f}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="numero-pourvoi" className="text-xs">N° de pourvoi</Label>
                  <Input
                    id="numero-pourvoi"
                    placeholder="ex: 21-14.490"
                    value={numeroPourvoi}
                    onChange={(e) => setNumeroPourvoi(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="date-decision" className="text-xs">Date de décision</Label>
                  <Input
                    id="date-decision"
                    type="date"
                    value={dateDecision}
                    onChange={(e) => setDateDecision(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="solution" className="text-xs">Solution</Label>
                  <Select value={solution} onValueChange={setSolution}>
                    <SelectTrigger id="solution">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {SOLUTION_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="col-span-2 space-y-1">
                  <Label htmlFor="publication" className="text-xs">Publication</Label>
                  <Select value={publication} onValueChange={setPublication}>
                    <SelectTrigger id="publication">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {PUBLICATION_OPTIONS.map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || !file || !sourceType}
            >
              {submitting ? "Upload en cours..." : "Ajouter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
