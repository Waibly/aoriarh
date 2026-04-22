"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  Edit,
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
import { Label } from "@/components/ui/label";
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
import { MetadataEditDialog } from "./metadata-edit-dialog";
import { useDocumentActions, type BulkResult } from "./use-document-actions";

// ----------------- Constants -----------------

const STATUS_LABEL: Record<string, string> = {
  pending: "En attente",
  indexing: "En cours",
  indexed: "Indexé",
  error: "Erreur",
};

const STATUS_CLASSES: Record<string, string> = {
  pending: "rounded-full border-slate-400 bg-slate-500/10 text-slate-600 dark:text-slate-300",
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
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [addCcnOpen, setAddCcnOpen] = useState(false);
  const [selectedNewCcn, setSelectedNewCcn] = useState<CcnReference[]>([]);
  const [installingCcn, setInstallingCcn] = useState(false);
  const [removeCcnIdcc, setRemoveCcnIdcc] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection>({ type: "category", key: "all" });

  // Debounce the search input: filtering happens 200 ms after the last
  // keystroke, not on every letter. Prevents a re-render burst when the
  // user types quickly.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 200);
    return () => clearTimeout(t);
  }, [search]);

  const initialLoadDone = useRef(false);
  // Tracks the organisation whose data is currently being fetched. Protects
  // against race conditions when the user switches orgs mid-fetch: the older
  // response won't overwrite the state once a newer request has started.
  const activeOrgIdRef = useRef<string | null>(null);

  const fetchDocuments = useCallback(async () => {
    if (!currentOrg || !token) return;
    const requestOrgId = currentOrg.id;
    activeOrgIdRef.current = requestOrgId;
    if (!initialLoadDone.current) setLoading(true);
    try {
      const [docs, ccns] = await Promise.all([
        apiFetch<Document[]>(`/documents/${currentOrg.id}/`, { token }),
        apiFetch<OrganisationConvention[]>(
          `/conventions/organisations/${currentOrg.id}`,
          { token },
        ).catch(() => [] as OrganisationConvention[]),
      ]);
      if (activeOrgIdRef.current !== requestOrgId) return; // stale response
      setDocuments(docs);
      setConventions(ccns);
      initialLoadDone.current = true;
    } catch (err) {
      if (activeOrgIdRef.current !== requestOrgId) return;
      toast.error(
        err instanceof Error
          ? err.message
          : "Impossible de charger les documents. Vérifiez votre connexion et réessayez.",
      );
    } finally {
      if (activeOrgIdRef.current === requestOrgId) setLoading(false);
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

  // ---- Document actions (single + bulk + metadata) ----

  const {
    handleDelete,
    handleDownload,
    handleReindex,
    handleReplace,
    handleBulkDelete,
    handleBulkReindex,
    handleUpdateMetadata,
  } = useDocumentActions({
    orgId: currentOrg?.id,
    token,
    onChanged: fetchDocuments,
  });

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
    if (debouncedSearch.trim()) {
      const q = debouncedSearch.toLowerCase();
      docs = docs.filter((d) => {
        const sourceLabel =
          SOURCE_TYPE_OPTIONS.find((s) => s.value === d.source_type)?.label ?? d.source_type;
        return d.name.toLowerCase().includes(q) || sourceLabel.toLowerCase().includes(q);
      });
    }
    return docs;
  }, [selection, internalDocs, debouncedSearch]);

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
            Tous les documents propres à votre organisation, utilisés par AORIA RH pour répondre à vos questions.
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
          <Card className="gap-1 py-2">
            <CardHeader className="pb-1 px-3 pt-1">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Library className="h-4 w-4" />
                Convention collective
                <InfoTooltip>
                  Convention(s) collective(s) installée(s) pour votre organisation.
                  Elle est récupérée depuis les sources officielles et utilisée
                  automatiquement par AORIA RH dans toutes vos questions.
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 p-2 pt-1">
              {loading && conventions.length === 0 ? (
                <Skeleton className="h-10 w-full" />
              ) : conventions.length === 0 ? (
                <div className="px-2 py-4 space-y-2">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    Installez votre convention collective pour qu&apos;AORIA RH
                    s&apos;y réfère automatiquement dans ses réponses.
                  </p>
                  {isManager && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="w-full"
                      onClick={() => setAddCcnOpen(true)}
                    >
                      <Plus className="h-3.5 w-3.5 mr-1" />
                      Installer ma convention
                    </Button>
                  )}
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
                        <div className="font-medium break-words whitespace-normal text-xs">
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
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
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
                  <Plus className="h-3.5 w-3.5 mr-1" />
                  Installer une convention
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Internal documents section */}
          <Card className="gap-1 py-2">
            <CardHeader className="pb-1 px-3 pt-1">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <FolderOpen className="h-4 w-4" />
                Vos documents
                <InfoTooltip>
                  Documents propres à votre organisation, classés par catégorie.
                  Tous sont indexés et disponibles pour AORIA RH.
                </InfoTooltip>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 p-2 pt-1">
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
              onBulkDelete={handleBulkDelete}
              onBulkReindex={handleBulkReindex}
              onUpdateMetadata={handleUpdateMetadata}
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
              Cette convention ne sera plus utilisée par AORIA RH pour répondre
              à vos questions. Vous pourrez la réinstaller à tout moment.
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
  onRemove,
  onDownload,
}: {
  ccn: OrganisationConvention;
  docs: Document[];
  isManager: boolean;
  onRemove: () => void;
  onDownload: (id: string) => void;
}) {
  // Split docs : consolidated official text vs recently published amendments.
  // The amendments list is read-only from the client's perspective — they
  // are common documents managed by AORIA RH and synchronised by the BOCC
  // cron. The user can neither modify, re-sync nor delete them from here.
  const consolidatedDocs = useMemo(
    () => docs.filter((d) => !d.name.includes("BOCC")),
    [docs],
  );
  const amendmentDocs = useMemo(
    () =>
      [...docs]
        .filter((d) => d.name.includes("BOCC"))
        .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [docs],
  );

  // Most recent avenant date — for the "Dernière maj" badge.
  const latestAvenantDate =
    amendmentDocs.length > 0 ? new Date(amendmentDocs[0].created_at) : null;

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
        return { color, label: `À jour au ${new Date(ccn.source_date).toLocaleDateString("fr-FR")}` };
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
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1" /> Active — utilisée par AORIA RH
                  </Badge>
                )}
                {(ccn.status === "fetching" || ccn.status === "indexing" || ccn.status === "pending") && (
                  <Badge className="bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border-0">
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                    {ccn.status === "fetching"
                      ? "Récupération du texte officiel (1-2 min)..."
                      : ccn.status === "indexing"
                        ? "Préparation pour le chat (30-60 s)..."
                        : "Démarrage..."}
                  </Badge>
                )}
                {ccn.status === "error" && (
                  <Badge className="bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 border-0">
                    Erreur — contactez le support
                  </Badge>
                )}
                {latestAvenantDate && (
                  <Badge variant="outline" className="rounded-full text-[11px]">
                    Dernier avenant le {latestAvenantDate.toLocaleDateString("fr-FR")}
                  </Badge>
                )}
              </div>
              {ccn.status === "error" && ccn.error_message && (
                <p className="text-xs text-destructive mt-2">{ccn.error_message}</p>
              )}
            </div>
            {isManager && (
              <div className="flex items-center gap-1 shrink-0">
                <Button variant="outline" size="sm" onClick={onRemove}>
                  <Trash2 className="h-3.5 w-3.5 mr-1 text-destructive" />
                  Retirer
                </Button>
              </div>
            )}
          </div>
        </CardHeader>
      </Card>

      {/* Tabs : contenu consolidé vs nouveautés BOCC */}
      <Tabs defaultValue="consolidated">
        <TabsList>
          <TabsTrigger value="consolidated">
            Ce que contient votre base
            <Badge variant="outline" className="ml-2 text-[10px] h-4 px-1.5">
              {consolidatedDocs.length}
            </Badge>
          </TabsTrigger>
          <TabsTrigger value="amendments">
            Nouveautés
            <Badge variant="outline" className="ml-2 text-[10px] h-4 px-1.5">
              {amendmentDocs.length}
            </Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="consolidated">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                Ce que contient votre base
                <InfoTooltip>
                  Le texte officiel consolidé de votre convention : articles
                  de base, parties législative et réglementaire, annexes
                  (classifications, régime prévoyance) et grilles de
                  salaires. Version à la date affichée en haut.
                </InfoTooltip>
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Le texte officiel de votre convention, complet et structuré.
                AORIA RH y puise pour chaque question que vous posez.
              </p>
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
                Nouveautés
                <InfoTooltip>
                  Avenants publiés au Bulletin officiel des conventions
                  collectives (BOCC), ajoutés automatiquement par AORIA RH
                  dès leur parution. AORIA RH les utilise au même titre que
                  le texte officiel. Lecture seule : ce sont des documents
                  partagés entre tous les clients qui ont installé cette
                  convention.
                </InfoTooltip>
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Les avenants publiés récemment, avant d&apos;être consolidés
                dans le texte officiel. Ajoutés automatiquement à chaque
                parution au BOCC.
              </p>
            </CardHeader>
            <CardContent>
              <DocsList
                docs={amendmentDocs}
                onDownload={onDownload}
                emptyText="Aucun avenant récent pour cette convention. Les nouveaux avenants seront ajoutés automatiquement dès leur publication."
                collapseAfter={5}
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
  collapseAfter,
}: {
  docs: Document[];
  onDownload: (id: string) => void;
  emptyText: string;
  /** When set, only show `collapseAfter` items initially and offer a
   *  "Voir les X plus anciens" button to reveal the rest. */
  collapseAfter?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  if (docs.length === 0) {
    return <div className="py-8 text-center text-xs text-muted-foreground">{emptyText}</div>;
  }

  const shouldCollapse = collapseAfter && docs.length > collapseAfter && !expanded;
  const visibleDocs = shouldCollapse ? docs.slice(0, collapseAfter) : docs;
  const hiddenCount = docs.length - (collapseAfter ?? 0);

  return (
    <div className="space-y-1">
      {visibleDocs.map((d) => (
        <div
          key={d.id}
          className="flex items-start gap-3 px-3 py-2 rounded border hover:bg-muted/30 transition-colors"
        >
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium break-words whitespace-normal">{cleanDocName(d.name)}</div>
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
            <Download className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}
      {shouldCollapse && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full text-center text-xs text-primary hover:underline py-2"
        >
          Voir les {hiddenCount} plus anciens
        </button>
      )}
      {expanded && collapseAfter && docs.length > collapseAfter && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="w-full text-center text-xs text-muted-foreground hover:underline py-2"
        >
          Réduire
        </button>
      )}
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
  onBulkDelete,
  onBulkReindex,
  onUpdateMetadata,
}: {
  category: CategoryDef;
  docs: Document[];
  loading: boolean;
  search: string;
  onSearchChange: (v: string) => void;
  isManager: boolean;
  onUpload: () => void;
  onDownload: (id: string) => void;
  onDelete: (id: string, name?: string) => void;
  onReindex: (id: string) => void;
  onReplace: (id: string, file: File) => void;
  onBulkDelete: (ids: string[]) => Promise<BulkResult | null>;
  onBulkReindex: (ids: string[]) => Promise<BulkResult | null>;
  onUpdateMetadata: (id: string, data: Record<string, string | null>) => Promise<boolean>;
}) {
  const Icon = category.icon;

  // Sort, filter by status, paginate — all local to the table.
  type SortKey = "name" | "source_type" | "indexation_status" | "file_size" | "created_at";
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 25;

  // Multi-selection for bulk actions (delete, reindex).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [editingDoc, setEditingDoc] = useState<Document | null>(null);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const sortedFiltered = useMemo(() => {
    let rows = docs;
    if (statusFilter !== "all") {
      rows = rows.filter((d) => {
        if (statusFilter === "indexed") return d.indexation_status === "indexed";
        if (statusFilter === "indexing") return d.indexation_status === "indexing" || d.indexation_status === "pending";
        if (statusFilter === "error") return d.indexation_status === "error";
        return true;
      });
    }
    const sorted = [...rows].sort((a, b) => {
      let va: string | number = "";
      let vb: string | number = "";
      switch (sortKey) {
        case "name":
          va = a.name.toLowerCase();
          vb = b.name.toLowerCase();
          break;
        case "source_type":
          va = a.source_type;
          vb = b.source_type;
          break;
        case "indexation_status":
          va = a.indexation_status;
          vb = b.indexation_status;
          break;
        case "file_size":
          va = a.file_size ?? 0;
          vb = b.file_size ?? 0;
          break;
        case "created_at":
          va = a.created_at;
          vb = b.created_at;
          break;
      }
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [docs, statusFilter, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sortedFiltered.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const paginated = useMemo(
    () => sortedFiltered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE),
    [sortedFiltered, currentPage],
  );

  // Reset to page 1 when filter/search changes
  useEffect(() => {
    setPage(1);
  }, [statusFilter, search, category.key]);

  // Clear the selection whenever the filter, search or category changes —
  // otherwise we'd keep IDs that are no longer visible, and "Tout
  // sélectionner" would be in a confusing partial state.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [statusFilter, search, category.key]);

  // Selection helpers
  const visibleIds = useMemo(() => new Set(paginated.map((d) => d.id)), [paginated]);
  const selectedVisibleCount = useMemo(
    () => paginated.filter((d) => selectedIds.has(d.id)).length,
    [paginated, selectedIds],
  );
  const allVisibleChecked = paginated.length > 0 && selectedVisibleCount === paginated.length;
  const someVisibleChecked = selectedVisibleCount > 0 && !allVisibleChecked;

  const toggleOne = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allVisibleChecked) {
        for (const id of visibleIds) next.delete(id);
      } else {
        for (const id of visibleIds) next.add(id);
      }
      return next;
    });
  };

  const runBulkDelete = async () => {
    setBulkBusy(true);
    const res = await onBulkDelete(Array.from(selectedIds));
    setBulkBusy(false);
    if (res) setSelectedIds(new Set());
  };

  const runBulkReindex = async () => {
    setBulkBusy(true);
    const res = await onBulkReindex(Array.from(selectedIds));
    setBulkBusy(false);
    if (res) setSelectedIds(new Set());
  };

  // Counts per status for the filter pills
  const statusCounts = useMemo(() => {
    const c = { all: docs.length, indexed: 0, indexing: 0, error: 0 };
    for (const d of docs) {
      if (d.indexation_status === "indexed") c.indexed++;
      else if (d.indexation_status === "indexing" || d.indexation_status === "pending") c.indexing++;
      else if (d.indexation_status === "error") c.error++;
    }
    return c;
  }, [docs]);

  const filterPills: { key: string; label: string; count: number; color: string }[] = [
    { key: "all", label: "Tous", count: statusCounts.all, color: "" },
    { key: "indexed", label: "Indexés", count: statusCounts.indexed, color: "text-green-600" },
    { key: "indexing", label: "En cours", count: statusCounts.indexing, color: "text-orange-600" },
    { key: "error", label: "Erreur", count: statusCounts.error, color: "text-destructive" },
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base flex items-center gap-2">
              <Icon className="h-4 w-4" />
              {category.label}
              <InfoTooltip>{category.help}</InfoTooltip>
              {loading && docs.length > 0 && (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-label="Actualisation en cours" />
              )}
            </CardTitle>
            <p className="text-xs text-muted-foreground mt-1">
              {docs.length} document{docs.length > 1 ? "s" : ""}
              {statusFilter !== "all" && sortedFiltered.length !== docs.length && (
                <span> · {sortedFiltered.length} filtré{sortedFiltered.length > 1 ? "s" : ""}</span>
              )}
            </p>
          </div>
          {isManager && (
            <Button size="sm" onClick={onUpload}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Ajouter
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="relative mb-3">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Rechercher dans cette catégorie..."
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>

        {/* Status filter pills */}
        <div className="flex flex-wrap gap-2 mb-4">
          {filterPills.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => setStatusFilter(p.key)}
              className={cn(
                "px-3 py-1 rounded-full text-xs font-medium border transition",
                statusFilter === p.key
                  ? "bg-primary/10 border-primary text-primary"
                  : "bg-background border-border text-muted-foreground hover:bg-muted",
              )}
              disabled={p.count === 0 && p.key !== "all"}
            >
              <span className={cn("tabular-nums", p.color)}>{p.count}</span>{" "}
              <span>{p.label}</span>
            </button>
          ))}
        </div>

        {loading && docs.length === 0 ? (
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : paginated.length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            {search.trim() || statusFilter !== "all"
              ? "Aucun document ne correspond à votre recherche ou filtre."
              : "Aucun document dans cette catégorie."}
          </div>
        ) : (
          <>
            {/* Bulk action bar — only shown when at least one row is selected */}
            {isManager && selectedIds.size > 0 && (
              <div className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-2">
                <span className="text-sm">
                  <strong>{selectedIds.size}</strong> document
                  {selectedIds.size > 1 ? "s" : ""} sélectionné{selectedIds.size > 1 ? "s" : ""}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={bulkBusy}
                    onClick={runBulkReindex}
                  >
                    <RefreshCw className="h-3.5 w-3.5 mr-1" />
                    Réindexer
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={bulkBusy}
                    onClick={() => setSelectedIds(new Set())}
                  >
                    Tout désélectionner
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={bulkBusy}
                    onClick={runBulkDelete}
                  >
                    {bulkBusy ? (
                      <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5 mr-1" />
                    )}
                    Supprimer
                  </Button>
                </div>
              </div>
            )}

            <Table>
              <TableHeader>
                <TableRow>
                  {isManager && (
                    <TableHead className="w-[40px]">
                      <input
                        type="checkbox"
                        aria-label="Tout sélectionner"
                        checked={allVisibleChecked}
                        ref={(el) => {
                          if (el) el.indeterminate = someVisibleChecked;
                        }}
                        onChange={toggleAllVisible}
                        className="h-4 w-4 cursor-pointer accent-primary"
                      />
                    </TableHead>
                  )}
                  <SortableHead label="Nom" sortKey="name" currentKey={sortKey} currentDir={sortDir} onSort={toggleSort} />
                  <SortableHead label="Type" sortKey="source_type" currentKey={sortKey} currentDir={sortDir} onSort={toggleSort} className="w-[160px]" />
                  <SortableHead label="Statut" sortKey="indexation_status" currentKey={sortKey} currentDir={sortDir} onSort={toggleSort} className="w-[100px]" />
                  <SortableHead label="Taille" sortKey="file_size" currentKey={sortKey} currentDir={sortDir} onSort={toggleSort} className="w-[80px] text-right" align="right" />
                  <SortableHead label="Date" sortKey="created_at" currentKey={sortKey} currentDir={sortDir} onSort={toggleSort} className="w-[100px] text-right" align="right" />
                  <TableHead className="w-[160px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginated.map((d) => (
                  <DocRow
                    key={d.id}
                    doc={d}
                    isManager={isManager}
                    isSelected={selectedIds.has(d.id)}
                    onToggleSelect={toggleOne}
                    onDownload={onDownload}
                    onDelete={onDelete}
                    onReindex={onReindex}
                    onReplace={onReplace}
                    onEditMetadata={() => setEditingDoc(d)}
                  />
                ))}
              </TableBody>
            </Table>

            {/* Metadata edit dialog */}
            <MetadataEditDialog
              doc={editingDoc}
              onClose={() => setEditingDoc(null)}
              onSave={async (data) => {
                if (!editingDoc) return;
                const ok = await onUpdateMetadata(editingDoc.id, data);
                if (ok) setEditingDoc(null);
              }}
            />

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4 text-sm">
                <span className="text-muted-foreground">
                  {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, sortedFiltered.length)} sur {sortedFiltered.length}
                </span>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage === 1}
                    onClick={() => setPage(currentPage - 1)}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="px-3 tabular-nums text-muted-foreground">
                    {currentPage} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={currentPage === totalPages}
                    onClick={() => setPage(currentPage + 1)}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SortableHead({
  label,
  sortKey,
  currentKey,
  currentDir,
  onSort,
  className,
  align,
}: {
  label: string;
  sortKey: "name" | "source_type" | "indexation_status" | "file_size" | "created_at";
  currentKey: string;
  currentDir: "asc" | "desc";
  onSort: (k: "name" | "source_type" | "indexation_status" | "file_size" | "created_at") => void;
  className?: string;
  align?: "right";
}) {
  const active = currentKey === sortKey;
  const Icon = !active ? ArrowUpDown : currentDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-foreground transition",
          active ? "text-foreground font-semibold" : "text-muted-foreground",
          align === "right" && "justify-end w-full",
        )}
      >
        {label}
        <Icon className="h-3 w-3 opacity-60" />
      </button>
    </TableHead>
  );
}

function DocRow({
  doc,
  isManager,
  isSelected = false,
  onToggleSelect,
  onDownload,
  onDelete,
  onReindex,
  onReplace,
  onEditMetadata,
}: {
  doc: Document;
  isManager: boolean;
  isSelected?: boolean;
  onToggleSelect?: (id: string) => void;
  onDownload: (id: string) => void;
  onDelete: (id: string, name?: string) => void;
  onReindex: (id: string) => void;
  onReplace: (id: string, file: File) => void;
  onEditMetadata?: () => void;
}) {
  const replaceRef = useRef<HTMLInputElement>(null);
  const sourceLabel =
    SOURCE_TYPE_OPTIONS.find((s) => s.value === doc.source_type)?.label ?? doc.source_type;

  return (
    <TableRow className={isSelected ? "bg-primary/5" : undefined}>
      {isManager && onToggleSelect && (
        <TableCell className="w-[40px]">
          <input
            type="checkbox"
            aria-label={`Sélectionner ${doc.name}`}
            checked={isSelected}
            onChange={() => onToggleSelect(doc.id)}
            className="h-4 w-4 cursor-pointer accent-primary"
          />
        </TableCell>
      )}
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
            <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
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
            <Download className="h-3.5 w-3.5" />
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
                <Replace className="h-3.5 w-3.5 text-blue-500" />
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
              <RefreshCw className="h-3.5 w-3.5 text-orange-500" />
            </Button>
          )}
          {isManager && onEditMetadata && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onEditMetadata}
              title="Modifier les métadonnées"
            >
              <Edit className="h-3.5 w-3.5" />
            </Button>
          )}
          {isManager && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onDelete(doc.id, doc.name)}
              title="Supprimer"
            >
              <Trash2 className="h-3.5 w-3.5 text-destructive" />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}
