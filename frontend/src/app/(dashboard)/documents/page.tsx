"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  CheckCircle2,
  ChevronRight,
  Download,
  FileText,
  FileUp,
  Files,
  FolderOpen,
  Library,
  Loader2,
  Plus,
  RefreshCw,
  Replace,
  ScrollText,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import { apiFetch, authFetch } from "@/lib/api";
import type { Document, OrganisationConvention, CcnReference } from "@/types/api";
import { SOURCE_TYPE_OPTIONS } from "@/types/api";
import { CcnSelector } from "@/components/ccn-selector";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
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
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { InfoTooltip } from "@/components/admin/info-tooltip";
import { cn } from "@/lib/utils";
import { UploadDialog } from "./upload-dialog";

// ----------------- Constants -----------------

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  indexing: "En cours",
  indexed: "Indexé",
  error: "Erreur",
};

const STATUS_CLASSES: Record<string, string> = {
  pending: "rounded-full",
  indexing: "rounded-full border-orange-400 bg-orange-500/10 text-orange-600 dark:text-orange-400",
  indexed: "rounded-full border-green-500 bg-green-500/10 text-green-600 dark:text-green-400",
  error: "rounded-full border-red-500 bg-red-500/10 text-red-600 dark:text-red-400",
};

interface CategoryDef {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  sourceTypes: string[];
  help: React.ReactNode;
}

const CATEGORIES: CategoryDef[] = [
  {
    key: "all",
    label: "Tous les documents",
    icon: Files,
    sourceTypes: [],
    help: "Vue agrégée de tous vos documents internes (hors conventions collectives).",
  },
  {
    key: "accords",
    label: "Accords collectifs",
    icon: ScrollText,
    sourceTypes: [
      "accord_entreprise",
      "accord_performance_collective",
      "accord_branche",
      "accord_national_interprofessionnel",
    ],
    help: "Accords collectifs propres à votre entreprise : accords d'entreprise, APC, accords de branche, ANI.",
  },
  {
    key: "rules",
    label: "Règles internes",
    icon: FolderOpen,
    sourceTypes: ["reglement_interieur", "engagement_unilateral", "usage_entreprise"],
    help: "Règlement intérieur, engagements unilatéraux (DUE), usages d'entreprise — règles fixées par l'employeur.",
  },
  {
    key: "contracts",
    label: "Contrats",
    icon: FileText,
    sourceTypes: ["contrat_travail"],
    help: "Modèles de contrats de travail et avenants types utilisés dans votre organisation.",
  },
  {
    key: "other",
    label: "Autres",
    icon: Files,
    sourceTypes: ["divers"],
    help: "Documents divers ne rentrant dans aucune autre catégorie (chartes, plans, notes…).",
  },
];

function formatFileSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// ----------------- Types -----------------

type Selection =
  | { type: "ccn"; idcc: string }
  | { type: "category"; key: string };

// ----------------- Page -----------------

export default function DocumentsPage() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const token = session?.access_token;

  const [documents, setDocuments] = useState<Document[]>([]);
  const [conventions, setConventions] = useState<OrganisationConvention[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [isManager, setIsManager] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [search, setSearch] = useState("");
  const [addCcnOpen, setAddCcnOpen] = useState(false);
  const [selectedNewCcn, setSelectedNewCcn] = useState<CcnReference[]>([]);
  const [installingCcn, setInstallingCcn] = useState(false);
  const [removeCcnIdcc, setRemoveCcnIdcc] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>({ type: "category", key: "all" });

  const initialLoadDone = useRef(false);

  const fetchDocuments = useCallback(async () => {
    if (!currentOrg || !token) return;
    if (!initialLoadDone.current) setLoading(true);
    try {
      const [docs, ccns] = await Promise.all([
        apiFetch<Document[]>(`/documents/${currentOrg.id}/`, { token }),
        apiFetch<OrganisationConvention[]>(
          `/conventions/organisations/${currentOrg.id}`,
          { token },
        ).catch(() => [] as OrganisationConvention[]),
      ]);
      setDocuments(docs);
      setConventions(ccns);
      initialLoadDone.current = true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du chargement des documents");
    } finally {
      setLoading(false);
    }
  }, [currentOrg, token]);

  useEffect(() => {
    initialLoadDone.current = false;
    fetchDocuments();
  }, [fetchDocuments]);

  // Polling : refresh while a document or CCN is being processed
  const hasPending = useMemo(() => {
    const pendingDocs = documents.some(
      (d) => d.indexation_status === "pending" || d.indexation_status === "indexing",
    );
    const pendingCcn = conventions.some(
      (c) => c.status === "pending" || c.status === "fetching" || c.status === "indexing",
    );
    return pendingDocs || pendingCcn;
  }, [documents, conventions]);

  useEffect(() => {
    if (!hasPending) return;
    const interval = setInterval(fetchDocuments, 5000);
    return () => clearInterval(interval);
  }, [hasPending, fetchDocuments]);

  useEffect(() => {
    setIsManager(
      session?.user?.role === "admin" || session?.user?.role === "manager",
    );
  }, [session]);

  // Default to first installed CCN if any (better UX than empty page)
  useEffect(() => {
    if (!initialLoadDone.current) return;
    if (selection.type === "category" && selection.key === "all" && conventions.length > 0) {
      const firstReady = conventions.find((c) => c.status === "ready");
      if (firstReady) {
        setSelection({ type: "ccn", idcc: firstReady.idcc });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conventions.length]);

  // ---- Document actions ----

  const handleDelete = async (docId: string) => {
    if (!currentOrg || !token) return;
    try {
      await apiFetch(`/documents/${currentOrg.id}/${docId}`, {
        method: "DELETE",
        token,
      });
      toast.success("Document supprimé");
      fetchDocuments();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de la suppression");
    }
  };

  const handleDownload = async (docId: string) => {
    if (!currentOrg || !token) return;
    try {
      const res = await authFetch(`/documents/${currentOrg.id}/${docId}/download`, { token });
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
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du téléchargement");
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
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de la réindexation");
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
      toast.error(err instanceof Error ? err.message : "Erreur lors du remplacement");
    }
  };

  // ---- CCN actions ----

  const handleInstallCcn = async () => {
    if (!currentOrg || !token || selectedNewCcn.length === 0) return;
    setInstallingCcn(true);
    try {
      for (const ccn of selectedNewCcn) {
        await apiFetch(`/conventions/organisations/${currentOrg.id}`, {
          method: "POST",
          token,
          body: JSON.stringify({ idcc: ccn.idcc }),
        });
      }
      toast.success(
        selectedNewCcn.length === 1
          ? "Convention en cours d'installation"
          : `${selectedNewCcn.length} conventions en cours d'installation`,
      );
      setSelectedNewCcn([]);
      setAddCcnOpen(false);
      fetchDocuments();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de l'installation");
    } finally {
      setInstallingCcn(false);
    }
  };

  const handleSyncCcn = async (idcc: string) => {
    if (!currentOrg || !token) return;
    try {
      await apiFetch(`/conventions/organisations/${currentOrg.id}/${idcc}/sync`, {
        method: "POST",
        token,
      });
      toast.success("Mise à jour lancée");
      fetchDocuments();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de la mise à jour");
    }
  };

  const handleRemoveCcn = async (idcc: string) => {
    if (!currentOrg || !token) return;
    try {
      await apiFetch(`/conventions/organisations/${currentOrg.id}/${idcc}`, {
        method: "DELETE",
        token,
      });
      toast.success("Convention retirée");
      setRemoveCcnIdcc(null);
      // If the removed CCN was selected, fall back to "all"
      if (selection.type === "ccn" && selection.idcc === idcc) {
        setSelection({ type: "category", key: "all" });
      }
      fetchDocuments();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors de la suppression");
    }
  };

  // ---- Drag & Drop ----

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
    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles && droppedFiles.length > 0) {
      setUploadOpen(true);
      setTimeout(() => {
        if (droppedFiles.length === 1) {
          window.dispatchEvent(new CustomEvent("dropped-file", { detail: droppedFiles[0] }));
        } else {
          window.dispatchEvent(new CustomEvent("dropped-files", { detail: Array.from(droppedFiles) }));
        }
      }, 100);
    }
  };

  // ---- Derived data ----

  // Internal docs (excluding CCN documents)
  const internalDocs = useMemo(
    () => documents.filter((d) => d.source_type !== "convention_collective_nationale"),
    [documents],
  );

  // Counts per category
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: internalDocs.length };
    for (const cat of CATEGORIES) {
      if (cat.key === "all") continue;
      counts[cat.key] = internalDocs.filter((d) => cat.sourceTypes.includes(d.source_type)).length;
    }
    return counts;
  }, [internalDocs]);

  // Documents to show in the main pane
  const filteredDocs = useMemo(() => {
    if (selection.type !== "category") return [];
    let docs: Document[];
    if (selection.key === "all") {
      docs = internalDocs;
    } else {
      const cat = CATEGORIES.find((c) => c.key === selection.key);
      if (!cat) return [];
      docs = internalDocs.filter((d) => cat.sourceTypes.includes(d.source_type));
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      docs = docs.filter((d) => {
        const sourceLabel =
          SOURCE_TYPE_OPTIONS.find((s) => s.value === d.source_type)?.label ?? d.source_type;
        return d.name.toLowerCase().includes(q) || sourceLabel.toLowerCase().includes(q);
      });
    }
    return docs;
  }, [selection, internalDocs, search]);

  if (!currentOrg) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <p className="text-muted-foreground">
          Aucune organisation sélectionnée. Créez ou rejoignez une organisation.
        </p>
      </div>
    );
  }

  const selectedCcn =
    selection.type === "ccn" ? conventions.find((c) => c.idcc === selection.idcc) ?? null : null;
  const selectedCategory =
    selection.type === "category"
      ? CATEGORIES.find((c) => c.key === selection.key) ?? CATEGORIES[0]
      : null;

  return (
    <div
      className="space-y-6"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Tous les documents propres à votre organisation, interrogeables par l&apos;IA.
          </p>
        </div>
        {isManager && (
          <Button onClick={() => setUploadOpen(true)}>
            <FileUp className="mr-2 h-4 w-4" />
            Ajouter un document
          </Button>
        )}
      </div>

      {dragging && (
        <div className="border-2 border-dashed border-primary rounded-lg p-12 text-center text-sm text-primary bg-primary/5">
          Déposez vos fichiers ici
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* ---- Sidebar ---- */}
        <div className="col-span-12 md:col-span-3 space-y-4">
          {/* Conventions section */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Library className="h-4 w-4" />
                Convention collective
                <InfoTooltip>
                  Convention(s) collective(s) installée(s) pour votre organisation.
                  Elle est récupérée depuis les sources officielles et utilisée
                  automatiquement par l&apos;IA dans toutes vos questions.
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 p-2">
              {loading && conventions.length === 0 ? (
                <Skeleton className="h-10 w-full" />
              ) : conventions.length === 0 ? (
                <div className="text-xs text-muted-foreground px-2 py-3 text-center">
                  Aucune convention installée
                </div>
              ) : (
                conventions.map((c) => {
                  const active = selection.type === "ccn" && selection.idcc === c.idcc;
                  return (
                    <button
                      key={c.id}
                      onClick={() => setSelection({ type: "ccn", idcc: c.idcc })}
                      className={cn(
                        "w-full text-left px-2 py-2 rounded text-sm flex items-center gap-2 transition-colors",
                        active ? "bg-accent text-accent-foreground" : "hover:bg-muted/50",
                      )}
                    >
                      {c.status === "ready" ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                      ) : c.status === "error" ? (
                        <X className="h-3.5 w-3.5 text-destructive shrink-0" />
                      ) : (
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-600 shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate text-xs">
                          {c.titre_court || c.titre || `IDCC ${c.idcc}`}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          IDCC {c.idcc}
                          {c.status === "ready" && c.articles_count != null
                            ? ` · ${c.articles_count} articles`
                            : c.status === "fetching"
                              ? " · téléchargement..."
                              : c.status === "indexing"
                                ? " · indexation..."
                                : c.status === "pending"
                                  ? " · en attente"
                                  : c.status === "error"
                                    ? " · erreur"
                                    : ""}
                        </div>
                      </div>
                      <ChevronRight className="h-3 w-3 shrink-0" />
                    </button>
                  );
                })
              )}
              {isManager && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start text-xs h-8"
                  onClick={() => setAddCcnOpen(true)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Installer une convention
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Internal documents section */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <FolderOpen className="h-4 w-4" />
                Vos documents
                <InfoTooltip>
                  Documents propres à votre organisation, classés par catégorie.
                  Tous sont indexés et disponibles pour l&apos;IA.
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 p-2">
              {CATEGORIES.map((cat) => {
                const Icon = cat.icon;
                const active = selection.type === "category" && selection.key === cat.key;
                const count = categoryCounts[cat.key] ?? 0;
                return (
                  <button
                    key={cat.key}
                    onClick={() => setSelection({ type: "category", key: cat.key })}
                    className={cn(
                      "w-full text-left px-2 py-2 rounded text-sm flex items-center gap-2 transition-colors",
                      active ? "bg-accent text-accent-foreground" : "hover:bg-muted/50",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="flex-1 truncate text-xs font-medium">{cat.label}</span>
                    <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                      {count}
                    </Badge>
                  </button>
                );
              })}
            </CardContent>
          </Card>
        </div>

        {/* ---- Main pane ---- */}
        <div className="col-span-12 md:col-span-9">
          {selectedCcn ? (
            <CcnDetailPane
              ccn={selectedCcn}
              docs={documents.filter(
                (d) =>
                  d.source_type === "convention_collective_nationale" &&
                  d.name.includes(`IDCC ${selectedCcn.idcc}`),
              )}
              isManager={isManager}
              onSync={() => handleSyncCcn(selectedCcn.idcc)}
              onRemove={() => setRemoveCcnIdcc(selectedCcn.idcc)}
              onDownload={handleDownload}
            />
          ) : selectedCategory ? (
            <CategoryPane
              category={selectedCategory}
              docs={filteredDocs}
              loading={loading}
              search={search}
              onSearchChange={setSearch}
              isManager={isManager}
              onUpload={() => setUploadOpen(true)}
              onDownload={handleDownload}
              onDelete={handleDelete}
              onReindex={handleReindex}
              onReplace={handleReplace}
            />
          ) : null}
        </div>
      </div>

      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        orgId={currentOrg.id}
        token={token}
        onUploaded={fetchDocuments}
        initialSourceType={
          selection.type === "category" && selection.key !== "all"
            ? CATEGORIES.find((c) => c.key === selection.key)?.sourceTypes[0]
            : undefined
        }
      />

      {/* Install CCN dialog */}
      <Dialog open={addCcnOpen} onOpenChange={setAddCcnOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Installer une convention collective</DialogTitle>
            <DialogDescription>
              Recherchez par IDCC ou par nom. La convention sera téléchargée
              depuis la source officielle puis indexée automatiquement.
            </DialogDescription>
          </DialogHeader>
          {token && (
            <CcnSelector
              token={token}
              selected={selectedNewCcn}
              onChange={setSelectedNewCcn}
            />
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setAddCcnOpen(false);
                setSelectedNewCcn([]);
              }}
            >
              Annuler
            </Button>
            <Button
              disabled={selectedNewCcn.length === 0 || installingCcn}
              onClick={handleInstallCcn}
            >
              {installingCcn ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Installation...
                </>
              ) : (
                "Installer"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* CCN removal confirmation */}
      <Dialog open={removeCcnIdcc !== null} onOpenChange={(open) => !open && setRemoveCcnIdcc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Retirer la convention collective</DialogTitle>
            <DialogDescription>
              Cette action supprimera la convention et tous ses documents indexés.
              Les réponses du chat ne pourront plus s&apos;appuyer sur cette convention.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveCcnIdcc(null)}>
              Annuler
            </Button>
            <Button
              variant="destructive"
              onClick={() => removeCcnIdcc && handleRemoveCcn(removeCcnIdcc)}
            >
              Retirer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ----------------- CCN Detail Pane -----------------

function CcnDetailPane({
  ccn,
  docs,
  isManager,
  onSync,
  onRemove,
  onDownload,
}: {
  ccn: OrganisationConvention;
  docs: Document[];
  isManager: boolean;
  onSync: () => void;
  onRemove: () => void;
  onDownload: (id: string) => void;
}) {
  // Split docs : consolidated official text vs recently published amendments
  const consolidatedDocs = docs.filter((d) => !d.name.includes("BOCC"));
  const amendmentDocs = docs.filter((d) => d.name.includes("BOCC"));

  // Source date freshness color
  const sourceDateBadge = ccn.source_date
    ? (() => {
        const ageMs = Date.now() - new Date(ccn.source_date).getTime();
        const ageYears = ageMs / (365.25 * 24 * 60 * 60 * 1000);
        const color =
          ageYears > 2
            ? "border-red-500 bg-red-500/10 text-red-700 dark:text-red-400"
            : ageYears > 1
              ? "border-orange-500 bg-orange-500/10 text-orange-700 dark:text-orange-400"
              : "border-green-500 bg-green-500/10 text-green-700 dark:text-green-400";
        return { color, label: `Textes au ${new Date(ccn.source_date).toLocaleDateString("fr-FR")}` };
      })()
    : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base">
                {ccn.titre || ccn.titre_court || `IDCC ${ccn.idcc}`}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-2 mt-2 text-xs">
                <Badge variant="outline" className="font-mono">
                  IDCC {ccn.idcc}
                </Badge>
                {ccn.articles_count != null && (
                  <Badge variant="outline">{ccn.articles_count} articles</Badge>
                )}
                {sourceDateBadge && (
                  <Badge variant="outline" className={`rounded-full text-[11px] ${sourceDateBadge.color}`}>
                    {sourceDateBadge.label}
                  </Badge>
                )}
                {ccn.status === "ready" && (
                  <Badge className="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 border-0">
                    <CheckCircle2 className="h-3 w-3 mr-1" /> Prête
                  </Badge>
                )}
                {(ccn.status === "fetching" || ccn.status === "indexing" || ccn.status === "pending") && (
                  <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-0">
                    <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    {ccn.status === "fetching"
                      ? "Téléchargement"
                      : ccn.status === "indexing"
                        ? "Indexation"
                        : "En attente"}
                  </Badge>
                )}
                {ccn.status === "error" && (
                  <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-0">
                    Erreur
                  </Badge>
                )}
              </div>
              {ccn.status === "error" && ccn.error_message && (
                <p className="text-xs text-destructive mt-2">{ccn.error_message}</p>
              )}
            </div>
            {isManager && (
              <div className="flex items-center gap-1 shrink-0">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onSync}
                  disabled={
                    ccn.status === "fetching" ||
                    ccn.status === "indexing" ||
                    ccn.status === "pending"
                  }
                >
                  <RefreshCw className="h-3 w-3 mr-1" />
                  Mettre à jour
                </Button>
                <Button variant="outline" size="sm" onClick={onRemove}>
                  <Trash2 className="h-3 w-3 mr-1 text-destructive" />
                  Retirer
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
      </Card>

      {/* Tabs : Texte consolidé / Avenants récents */}
      <Tabs defaultValue="consolidated">
        <TabsList>
          <TabsTrigger value="consolidated">
            Texte officiel
            <Badge variant="outline" className="ml-2 text-[10px] h-4 px-1.5">
              {consolidatedDocs.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="amendments">
            Avenants récents
            <Badge variant="outline" className="ml-2 text-[10px] h-4 px-1.5">
              {amendmentDocs.length}
            </Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="consolidated">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                Texte officiel consolidé
                <InfoTooltip>
                  Texte officiel de votre convention collective, à jour à la
                  date affichée en haut. Contient les articles structurés
                  (texte de base, parties législative et réglementaire,
                  avenants et annexes intégrés).
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <DocsList
                docs={consolidatedDocs}
                onDownload={onDownload}
                emptyText="Aucun texte officiel disponible"
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="amendments">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                Avenants récents
                <InfoTooltip>
                  Avenants publiés récemment qui complètent le texte officiel
                  avant que celui-ci ne soit consolidé. L&apos;IA s&apos;appuie
                  aussi sur ces avenants pour répondre aux questions.
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <DocsList
                docs={amendmentDocs}
                onDownload={onDownload}
                emptyText="Aucun avenant récent pour cette convention"
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Strip internal source markers (BOCC, KALI, Légifrance) from doc names
 * before showing them to end users. These references are internal sourcing
 * details and should never leak to the customer-facing UI. */
function cleanDocName(name: string): string {
  return name
    .replace(/\bBOCC\s*\d{4}-\d{2}\s*[—-]?\s*/gi, "")
    .replace(/\bBOCC\s*[—-]?\s*/gi, "")
    .replace(/\bKALI\b/gi, "")
    .replace(/\bLégifrance\b/gi, "")
    .replace(/\s+—\s+—/g, " —")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function DocsList({
  docs,
  onDownload,
  emptyText,
}: {
  docs: Document[];
  onDownload: (id: string) => void;
  emptyText: string;
}) {
  if (docs.length === 0) {
    return <div className="py-8 text-center text-xs text-muted-foreground">{emptyText}</div>;
  }
  return (
    <div className="space-y-1">
      {docs.map((d) => (
        <div
          key={d.id}
          className="flex items-center gap-3 px-3 py-2 rounded border hover:bg-muted/30 transition-colors"
        >
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate">{cleanDocName(d.name)}</div>
            <div className="text-[11px] text-muted-foreground">
              {formatDate(d.created_at)} · {formatFileSize(d.file_size)}
              {d.indexation_status !== "indexed" && (
                <Badge
                  variant="outline"
                  className={`ml-2 text-[10px] h-4 ${STATUS_CLASSES[d.indexation_status] ?? ""}`}
                >
                  {STATUS_LABEL[d.indexation_status] ?? d.indexation_status}
                </Badge>
              )}
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onDownload(d.id)}
            title="Télécharger"
          >
            <Download className="h-3 w-3" />
          </Button>
        </div>
      ))}
    </div>
  );
}

// ----------------- Category Pane -----------------

function CategoryPane({
  category,
  docs,
  loading,
  search,
  onSearchChange,
  isManager,
  onUpload,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
}: {
  category: CategoryDef;
  docs: Document[];
  loading: boolean;
  search: string;
  onSearchChange: (v: string) => void;
  isManager: boolean;
  onUpload: () => void;
  onDownload: (id: string) => void;
  onDelete: (id: string) => void;
  onReindex: (id: string) => void;
  onReplace: (id: string, file: File) => void;
}) {
  const Icon = category.icon;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base flex items-center gap-2">
              <Icon className="h-4 w-4" />
              {category.label}
              <InfoTooltip>{category.help}</InfoTooltip>
            </CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              {docs.length} document{docs.length > 1 ? "s" : ""}
            </p>
          </div>
          {isManager && (
            <Button size="sm" onClick={onUpload}>
              <Plus className="h-3 w-3 mr-1" />
              Ajouter
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="relative mb-4">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher dans cette catégorie..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>

        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : docs.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            {search.trim()
              ? "Aucun document ne correspond à votre recherche."
              : "Aucun document dans cette catégorie."}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead className="w-[160px]">Type</TableHead>
                <TableHead className="w-[100px]">Statut</TableHead>
                <TableHead className="w-[80px] text-right">Taille</TableHead>
                <TableHead className="w-[100px] text-right">Date</TableHead>
                <TableHead className="w-[140px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((d) => (
                <DocRow
                  key={d.id}
                  doc={d}
                  isManager={isManager}
                  onDownload={onDownload}
                  onDelete={onDelete}
                  onReindex={onReindex}
                  onReplace={onReplace}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function DocRow({
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
    SOURCE_TYPE_OPTIONS.find((s) => s.value === doc.source_type)?.label ?? doc.source_type;

  return (
    <TableRow>
      <TableCell className="max-w-[300px] font-medium">
        <span className="line-clamp-2 break-words text-sm">{cleanDocName(doc.name)}</span>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">{sourceLabel}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={STATUS_CLASSES[doc.indexation_status] ?? "rounded-full"}
        >
          {doc.indexation_status === "indexing" && (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          )}
          <span className="text-[10px]">
            {STATUS_LABEL[doc.indexation_status] ?? doc.indexation_status}
          </span>
        </Badge>
      </TableCell>
      <TableCell className="text-xs text-right text-muted-foreground">
        {formatFileSize(doc.file_size)}
      </TableCell>
      <TableCell className="text-xs text-right text-muted-foreground">
        {new Date(doc.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => onDownload(doc.id)} title="Télécharger">
            <Download className="h-3 w-3" />
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
                size="sm"
                onClick={() => replaceRef.current?.click()}
                title="Remplacer le fichier"
              >
                <Replace className="h-3 w-3 text-blue-500" />
              </Button>
            </>
          )}
          {doc.indexation_status === "error" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onReindex(doc.id)}
              title="Réindexer"
            >
              <RefreshCw className="h-3 w-3 text-orange-500" />
            </Button>
          )}
          {isManager && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(doc.id)}
              title="Supprimer"
            >
              <Trash2 className="h-3 w-3 text-destructive" />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}
