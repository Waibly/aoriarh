"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { ClipboardList, Download, Loader2, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import {
  listFiches,
  deleteFiche,
  downloadFicheById,
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
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
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

  const handleDownload = useCallback(
    async (fiche: Fiche) => {
      if (!token || downloadingId) return;
      setDownloadingId(fiche.id);
      try {
        await downloadFicheById(fiche.id, token);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Le téléchargement a échoué.");
      } finally {
        setDownloadingId(null);
      }
    },
    [token, downloadingId],
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
    <div className="mx-auto w-full max-w-4xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Fiches pratiques</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Les fiches que vous avez générées depuis vos réponses. Le PDF est
          recréé à chaque téléchargement, avec la date du jour.
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20 w-full rounded-xl" />
          ))}
        </div>
      ) : fiches.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <div className="bg-muted flex size-12 items-center justify-center rounded-full">
              <ClipboardList className="text-muted-foreground size-6" />
            </div>
            <p className="font-medium">Aucune fiche pratique pour l'instant</p>
            <p className="text-muted-foreground max-w-md text-sm">
              Posez une question dans le chat, puis cliquez sur « Fiche pratique »
              sous une réponse pour la transformer en fiche imprimable. Elle
              apparaîtra ici.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {fiches.map((fiche) => {
            const months = monthsSince(fiche.created_at);
            const stale =
              (Date.now() - new Date(fiche.created_at).getTime()) / 86_400_000 >
              STALE_AFTER_DAYS;
            return (
              <Card key={fiche.id}>
                <CardContent className="flex flex-wrap items-center gap-4 py-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{fiche.title}</p>
                    <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <span>Créée le {formatDate(fiche.created_at)}</span>
                      {stale && (
                        <Badge
                          variant="outline"
                          className="border-amber-500/40 text-amber-600 dark:text-amber-400"
                        >
                          <TriangleAlert className="mr-1 size-3" />
                          Il y a {months} mois — à vérifier
                        </Badge>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      variant="outline"
                      size="sm"
                      className="gap-1.5 border-primary/40 bg-transparent text-primary hover:bg-primary/10 hover:text-primary"
                      onClick={() => handleDownload(fiche)}
                      disabled={downloadingId === fiche.id}
                    >
                      {downloadingId === fiche.id ? (
                        <Loader2 className="size-4 animate-spin" />
                      ) : (
                        <Download className="size-4" />
                      )}
                      PDF
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="text-muted-foreground hover:text-destructive"
                      onClick={() => setToDelete(fiche)}
                      aria-label="Supprimer la fiche"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && setToDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette fiche ?</DialogTitle>
            <DialogDescription>
              « {toDelete?.title} » sera définitivement supprimée. Vous pourrez la
              régénérer depuis la réponse d'origine dans le chat.
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
