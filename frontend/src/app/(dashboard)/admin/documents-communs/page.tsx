"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Download,
  FileUp,
  Loader2,
  RefreshCw,
  Replace,
  Trash2,
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


export default function DocumentsCommunsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  const initialLoadDone = useRef(false);

  const fetchDocuments = useCallback(async () => {
    if (!token) return;
    if (!initialLoadDone.current) setLoading(true);
    try {
      const docs = await apiFetch<Document[]>("/admin/documents/", { token });
      setDocuments(docs);
      initialLoadDone.current = true;
    } catch {
      toast.error("Erreur lors du chargement des documents communs");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    initialLoadDone.current = false;
    fetchDocuments();
  }, [fetchDocuments]);

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

  const handleDelete = async (docId: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/documents/${docId}`, {
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
    if (!token) return;
    try {
      const res = await authFetch(`/admin/documents/${docId}/download`, {
        token,
      });
      if (!res.ok) throw new Error("Erreur");
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition");
      const filename = disposition?.match(/filename="(.+)"/)?.[1] ?? "document";
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

  const handleReindex = async (docId: string) => {
    if (!token) return;
    try {
      await apiFetch(`/admin/documents/${docId}/reindex`, {
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

  const totalPages = Math.max(1, Math.ceil(documents.length / PAGE_SIZE));
  const paginatedDocs = useMemo(
    () => documents.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [documents, page],
  );

  // Reset to page 1 when documents change (e.g. after upload/delete)
  useEffect(() => {
    if (page > totalPages) setPage(1);
  }, [totalPages, page]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Documents communs</h1>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>Base documentaire commune</CardTitle>
            <CardDescription>
              {documents.length} document{documents.length !== 1 ? "s" : ""} —
              partagés avec toutes les organisations
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
              Aucun document commun. Ajoutez le Code du travail ou une
              convention collective.
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40%]">Nom</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Statut</TableHead>
                    <TableHead>Format</TableHead>
                    <TableHead>Taille</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paginatedDocs.map((doc) => (
                    <CommonDocRow
                      key={doc.id}
                      doc={doc}
                      onDownload={handleDownload}
                      onDelete={handleDelete}
                      onReindex={handleReindex}
                      onReplace={handleReplace}
                    />
                  ))}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t pt-4 mt-4">
                  <p className="text-sm text-muted-foreground">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, documents.length)} sur {documents.length}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      Précédent
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      {page} / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Suivant
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <CommonUploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        token={token}
        onUploaded={fetchDocuments}
      />
    </div>
  );
}

/* ---- Document Row ---- */

function CommonDocRow({
  doc,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
}: {
  doc: Document;
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
      <TableCell className="truncate font-medium">
        {doc.name}
      </TableCell>
      <TableCell className="text-sm">{sourceLabel}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={STATUS_CLASSES[doc.indexation_status] ?? "rounded-full"}
        >
          {doc.indexation_status === "indexing" && (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          )}
          {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
        </Badge>
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
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onDelete(doc.id)}
            title="Supprimer"
          >
            <Trash2 className="h-4 w-4 text-destructive" />
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

  const selectedOption = SOURCE_TYPE_OPTIONS.find(
    (s) => s.value === sourceType
  );
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
        // Batch upload — multiple files, same source_type, no jurisprudence metadata
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
          toast.success(`${data.succeeded} document${data.succeeded > 1 ? "s" : ""} commun${data.succeeded > 1 ? "s" : ""} ajouté${data.succeeded > 1 ? "s" : ""}`);
        }
      } else {
        // Single upload — with full metadata support
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
      setError(
        err instanceof Error ? err.message : "Erreur lors de l'upload"
      );
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
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="text-destructive hover:underline shrink-0"
                    >
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

          {isJurisprudence && !isBatch && (
            <div className="space-y-3 rounded-md border border-border bg-muted/50 p-4">
              <p className="text-sm font-medium">Métadonnées jurisprudence</p>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="c-juridiction" className="text-xs">Juridiction</Label>
                  <Select value={juridiction} onValueChange={setJuridiction}>
                    <SelectTrigger id="c-juridiction">
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
                  <Label htmlFor="c-chambre" className="text-xs">Chambre</Label>
                  <Select value={chambre} onValueChange={setChambre}>
                    <SelectTrigger id="c-chambre">
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
                  <Label htmlFor="c-formation" className="text-xs">Formation</Label>
                  <Select value={formation} onValueChange={setFormation}>
                    <SelectTrigger id="c-formation">
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
                  <Label htmlFor="c-numero-pourvoi" className="text-xs">N° de pourvoi</Label>
                  <Input
                    id="c-numero-pourvoi"
                    placeholder="ex: 21-14.490"
                    value={numeroPourvoi}
                    onChange={(e) => setNumeroPourvoi(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="c-date-decision" className="text-xs">Date de décision</Label>
                  <Input
                    id="c-date-decision"
                    type="date"
                    value={dateDecision}
                    onChange={(e) => setDateDecision(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="c-solution" className="text-xs">Solution</Label>
                  <Select value={solution} onValueChange={setSolution}>
                    <SelectTrigger id="c-solution">
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
                  <Label htmlFor="c-publication" className="text-xs">Publication</Label>
                  <Select value={publication} onValueChange={setPublication}>
                    <SelectTrigger id="c-publication">
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

          {isBatch && isJurisprudence && (
            <p className="text-xs text-muted-foreground">
              Les métadonnées de jurisprudence ne sont pas disponibles en upload par lot.
            </p>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || files.length === 0 || !sourceType}
            >
              {submitting
                ? "Upload en cours..."
                : files.length > 1
                  ? `Ajouter ${files.length} documents`
                  : "Ajouter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
