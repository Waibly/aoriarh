"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import {
  ClipboardList,
  Download,
  Eye,
  Loader2,
  MessageCircle,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import {
  listFiches,
  deleteFiche,
  downloadFicheById,
  viewFicheById,
  type Fiche,
} from "@/lib/fiches-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// Au-delà de ce seuil, on signale que la fiche peut être périmée (le droit
// social bouge) et invite à la régénérer.
const STALE_AFTER_DAYS = 90;
type FreshnessFilter = "all" | "current" | "stale";

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

function monthsSince(value: string): number {
  const days = (Date.now() - new Date(value).getTime()) / 86_400_000;
  return Math.floor(days / 30);
}

function isStale(value: string): boolean {
  return (
    (Date.now() - new Date(value).getTime()) / 86_400_000 > STALE_AFTER_DAYS
  );
}

function normalizeSearch(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("fr-FR");
}

export default function FichesPage() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const token = session?.access_token;

  const [fiches, setFiches] = useState<Fiche[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Fiche | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [search, setSearch] = useState("");
  const [freshnessFilter, setFreshnessFilter] =
    useState<FreshnessFilter>("all");

  const filteredFiches = useMemo(() => {
    const normalizedSearch = normalizeSearch(search.trim());

    return fiches.filter((fiche) => {
      const stale = isStale(fiche.updated_at);
      const matchesSearch =
        normalizedSearch.length === 0 ||
        normalizeSearch(fiche.title).includes(normalizedSearch);
      const matchesFreshness =
        freshnessFilter === "all" ||
        (freshnessFilter === "stale" ? stale : !stale);

      return matchesSearch && matchesFreshness;
    });
  }, [fiches, freshnessFilter, search]);

  const fetchFiches = useCallback(async () => {
    if (!currentOrg || !token) return;
    setLoading(true);
    try {
      const data = await listFiches(currentOrg.id, token);
      setFiches(data);
    } catch {
      toast.error("Impossible de charger vos fiches pratiques.");
    } finally {
      setLoading(false);
    }
  }, [currentOrg, token]);

  useEffect(() => {
    fetchFiches();
  }, [fetchFiches]);

  const handleView = useCallback(
    async (fiche: Fiche) => {
      if (!token || busyId) return;
      setBusyId(fiche.id);
      try {
        await viewFicheById(fiche.id, token);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "L'aperçu a échoué.");
      } finally {
        setBusyId(null);
      }
    },
    [token, busyId]
  );

  const handleDownload = useCallback(
    async (fiche: Fiche) => {
      if (!token || busyId) return;
      setBusyId(fiche.id);
      try {
        await downloadFicheById(fiche.id, token);
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Le téléchargement a échoué."
        );
      } finally {
        setBusyId(null);
      }
    },
    [token, busyId]
  );

  const handleDelete = useCallback(async () => {
    if (!token || !toDelete) return;
    setDeleting(true);
    try {
      await deleteFiche(toDelete.id, token);
      setFiches((prev) => prev.filter((f) => f.id !== toDelete.id));
      toast.success("Fiche supprimée.");
      setToDelete(null);
    } catch {
      toast.error("La suppression a échoué.");
    } finally {
      setDeleting(false);
    }
  }, [token, toDelete]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">
          Fiches pratiques
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Les fiches que vous avez générées depuis vos réponses. La date
          affichée dans le PDF correspond à la dernière génération du contenu.
        </p>
      </div>
      <div className="dark:bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="w-full min-w-0 p-2 sm:p-4">
            {loading ? (
              <div className="space-y-3">
                <Skeleton className="h-9 w-full max-w-sm" />
                <div className="overflow-hidden rounded-lg border">
                  <Skeleton className="h-10 w-full rounded-none" />
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton
                      key={i}
                      className="h-14 w-full rounded-none border-t"
                    />
                  ))}
                </div>
              </div>
            ) : fiches.length === 0 ? (
              <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-14 text-center">
                <div className="bg-muted flex size-12 items-center justify-center rounded-full">
                  <ClipboardList className="text-muted-foreground size-6" />
                </div>
                <p className="font-medium">
                  Aucune fiche pratique pour l&apos;instant
                </p>
                <p className="text-muted-foreground max-w-md text-sm">
                  Posez une question dans le chat, puis cliquez sur « Créer une
                  fiche pratique » sous une réponse. Elle apparaîtra ici.
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="relative w-full sm:max-w-sm">
                    <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                    <Input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Rechercher une fiche…"
                      aria-label="Rechercher une fiche par titre"
                      className="pl-9"
                    />
                  </div>
                  <Select
                    value={freshnessFilter}
                    onValueChange={(value) =>
                      setFreshnessFilter(value as FreshnessFilter)
                    }
                  >
                    <SelectTrigger
                      className="w-full sm:w-[180px]"
                      aria-label="Filtrer par statut"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">Toutes les fiches</SelectItem>
                      <SelectItem value="current">À jour</SelectItem>
                      <SelectItem value="stale">À vérifier</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="overflow-hidden rounded-lg border">
                  <Table>
                    <TableHeader className="bg-muted/40">
                      <TableRow>
                        <TableHead>Titre</TableHead>
                        <TableHead className="w-[220px]">Mise à jour</TableHead>
                        <TableHead className="w-[170px]">Statut</TableHead>
                        <TableHead className="w-[132px] text-right">
                          Actions
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredFiches.length === 0 ? (
                        <TableRow>
                          <TableCell
                            colSpan={4}
                            className="text-muted-foreground h-28 text-center"
                          >
                            Aucune fiche ne correspond à vos filtres.
                          </TableCell>
                        </TableRow>
                      ) : (
                        filteredFiches.map((fiche) => {
                          const months = monthsSince(fiche.updated_at);
                          const stale = isStale(fiche.updated_at);
                          const busy = busyId === fiche.id;

                          return (
                            <TableRow key={fiche.id}>
                              <TableCell className="min-w-[280px] whitespace-normal">
                                <div className="flex items-center gap-3">
                                  <div className="bg-primary/10 flex size-9 shrink-0 items-center justify-center rounded-lg">
                                    <ClipboardList className="text-primary size-5" />
                                  </div>
                                  <button
                                    type="button"
                                    className="hover:text-primary focus-visible:ring-ring/50 cursor-pointer text-left font-medium underline-offset-4 outline-none hover:underline focus-visible:rounded-sm focus-visible:ring-[3px]"
                                    onClick={() => handleView(fiche)}
                                    disabled={busy}
                                  >
                                    {fiche.title}
                                  </button>
                                </div>
                              </TableCell>
                              <TableCell className="text-muted-foreground">
                                {formatDate(fiche.updated_at)}
                              </TableCell>
                              <TableCell>
                                {stale ? (
                                  <Badge
                                    variant="outline"
                                    className="border-amber-500/40 text-amber-600 dark:text-amber-400"
                                  >
                                    <TriangleAlert className="mr-1 size-3" />
                                    {months} mois — à vérifier
                                  </Badge>
                                ) : (
                                  <Badge
                                    variant="outline"
                                    className="border-emerald-500/40 text-emerald-700 dark:text-emerald-400"
                                  >
                                    À jour
                                  </Badge>
                                )}
                              </TableCell>
                              <TableCell className="text-right">
                                <div className="flex items-center justify-end gap-0.5">
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      {fiche.conversation_id ? (
                                        <Button
                                          variant="ghost"
                                          size="icon-sm"
                                          className="text-muted-foreground hover:text-primary"
                                          asChild
                                        >
                                          <Link
                                            href={`/chat/${fiche.conversation_id}`}
                                            aria-label="Ouvrir la conversation d'origine"
                                          >
                                            <MessageCircle className="size-4" />
                                          </Link>
                                        </Button>
                                      ) : (
                                        <Button
                                          variant="ghost"
                                          size="icon-sm"
                                          className="text-muted-foreground"
                                          disabled
                                          aria-label="Conversation d'origine indisponible"
                                        >
                                          <MessageCircle className="size-4" />
                                        </Button>
                                      )}
                                    </TooltipTrigger>
                                    <TooltipContent>
                                      {fiche.conversation_id
                                        ? "Ouvrir la conversation"
                                        : "Conversation indisponible"}
                                    </TooltipContent>
                                  </Tooltip>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon-sm"
                                        className="text-muted-foreground hover:text-primary"
                                        onClick={() => handleView(fiche)}
                                        disabled={busy}
                                        aria-label="Voir la fiche"
                                      >
                                        {busy ? (
                                          <Loader2 className="size-4 animate-spin" />
                                        ) : (
                                          <Eye className="size-4" />
                                        )}
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Voir</TooltipContent>
                                  </Tooltip>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon-sm"
                                        className="text-muted-foreground hover:text-primary"
                                        onClick={() => handleDownload(fiche)}
                                        disabled={busy}
                                        aria-label="Télécharger la fiche"
                                      >
                                        <Download className="size-4" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Télécharger</TooltipContent>
                                  </Tooltip>
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        variant="ghost"
                                        size="icon-sm"
                                        className="text-muted-foreground hover:text-destructive"
                                        onClick={() => setToDelete(fiche)}
                                        aria-label="Supprimer la fiche"
                                      >
                                        <Trash2 className="size-4" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Supprimer</TooltipContent>
                                  </Tooltip>
                                </div>
                              </TableCell>
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>
                </div>
                <p className="text-muted-foreground text-xs">
                  {filteredFiches.length} fiche
                  {filteredFiches.length > 1 ? "s" : ""} affichée
                  {filteredFiches.length > 1 ? "s" : ""} sur {fiches.length}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      <Dialog
        open={toDelete !== null}
        onOpenChange={(open) => !open && setToDelete(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette fiche ?</DialogTitle>
            <DialogDescription>
              « {toDelete?.title} » sera définitivement supprimée. Vous pourrez
              la régénérer depuis la réponse d&apos;origine dans le chat.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setToDelete(null)}
              disabled={deleting}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting && <Loader2 className="size-4 animate-spin" />}
              Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
