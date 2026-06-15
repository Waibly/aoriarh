"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { ClipboardList, Download, Eye, Loader2, Trash2, TriangleAlert } from "lucide-react";
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
import { Card, CardContent } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";

// Au-delà de ce seuil, on signale que la fiche peut être périmée (le droit
// social bouge) et invite à la régénérer.
const STALE_AFTER_DAYS = 90;

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

export default function FichesPage() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const token = session?.access_token;

  const [fiches, setFiches] = useState<Fiche[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Fiche | null>(null);
  const [deleting, setDeleting] = useState(false);

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
    [token, busyId],
  );

  const handleDownload = useCallback(
    async (fiche: Fiche) => {
      if (!token || busyId) return;
      setBusyId(fiche.id);
      try {
        await downloadFicheById(fiche.id, token);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Le téléchargement a échoué.");
      } finally {
        setBusyId(null);
      }
    },
    [token, busyId],
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
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-white p-4 dark:bg-card">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="w-full min-w-0 space-y-4 px-2 py-1 sm:px-4">
          <div>
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <ClipboardList className="h-5 w-5 text-primary" />
              Fiches pratiques
            </h1>
            <p className="text-muted-foreground mt-1 text-sm">
              Les fiches que vous avez générées depuis vos réponses. Le PDF est
              recréé à chaque téléchargement, avec la date du jour.
            </p>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-44 w-full rounded-xl" />
              ))}
            </div>
          ) : fiches.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
                <div className="bg-muted flex size-12 items-center justify-center rounded-full">
                  <ClipboardList className="text-muted-foreground size-6" />
                </div>
                <p className="font-medium">Aucune fiche pratique pour l&apos;instant</p>
                <p className="text-muted-foreground max-w-md text-sm">
                  Posez une question dans le chat, puis cliquez sur « Créer une
                  fiche pratique » sous une réponse. Elle apparaîtra ici.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {fiches.map((fiche) => {
                const months = monthsSince(fiche.created_at);
                const stale =
                  (Date.now() - new Date(fiche.created_at).getTime()) / 86_400_000 >
                  STALE_AFTER_DAYS;
                const busy = busyId === fiche.id;
                return (
                  <Card
                    key={fiche.id}
                    className="group flex flex-col gap-0 overflow-hidden border border-primary/15 bg-primary/5 py-0 transition-all duration-200 hover:scale-[1.02] hover:shadow-md dark:bg-primary/10"
                  >
                    <CardContent className="flex flex-1 flex-col gap-2 p-4">
                      <div className="bg-primary/10 flex size-9 items-center justify-center rounded-lg">
                        <ClipboardList className="text-primary size-5" />
                      </div>
                      <p className="line-clamp-2 text-sm font-semibold leading-snug">
                        {fiche.title}
                      </p>
                      <p className="text-muted-foreground mt-auto text-xs">
                        Créée le {formatDate(fiche.created_at)}
                      </p>
                      {stale && (
                        <Badge
                          variant="outline"
                          className="w-fit border-amber-500/40 text-amber-600 dark:text-amber-400"
                        >
                          <TriangleAlert className="mr-1 size-3" />
                          {months} mois — à vérifier
                        </Badge>
                      )}
                    </CardContent>
                    <div className="flex items-center justify-end gap-0.5 border-t border-primary/10 px-2 py-1.5">
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
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette fiche ?</DialogTitle>
            <DialogDescription>
              « {toDelete?.title} » sera définitivement supprimée. Vous pourrez la
              régénérer depuis la réponse d&apos;origine dans le chat.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setToDelete(null)} disabled={deleting}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting && <Loader2 className="size-4 animate-spin" />}
              Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
