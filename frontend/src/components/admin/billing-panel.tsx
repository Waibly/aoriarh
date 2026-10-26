"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import { ACCOUNT_STATUS_LABELS } from "@/lib/admin-labels";
import { Trash2, Download, XCircle } from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getPlanLabel } from "@/lib/plans";

type SubscriptionRow = {
  subscription_id: string;
  account_id: string;
  account_name: string | null;
  owner_email: string | null;
  plan: string;
  billing_cycle: string;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  created_at: string | null;
  mrr_contribution_cents: number;
};

type PendingPurgeRow = {
  account_id: string;
  account_name: string;
  owner_email: string;
  reason: string;
  eligible_since: string;
};

type StripeStatus = {
  configured: boolean;
  mode: "test" | "live" | "unknown" | null;
  webhook_configured: boolean;
};

const STATUS_COLORS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  trialing: "secondary",
  past_due: "destructive",
  canceled: "destructive",
  unpaid: "destructive",
};

const REASON_LABELS: Record<string, string> = {
  trial_expired: "Essai expiré (>30 j)",
  canceled: "Résiliation (>30 j)",
  unpaid: "Impayé (>60 j)",
};

export function BillingPanel({
  accountId,
  accountName,
  lifecycle = false,
  onErased,
}: {
  accountId?: string;
  accountName?: string;
  lifecycle?: boolean;
  onErased?: () => void;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [loaded, setLoaded] = useState(false);
  const [subs, setSubs] = useState<SubscriptionRow[]>([]);
  const [pending, setPending] = useState<PendingPurgeRow[]>([]);
  const [stripeStatus, setStripeStatus] = useState<StripeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<{
    id: string;
    email: string | null;
  } | null>(null);
  const [eraseTarget, setEraseTarget] = useState<PendingPurgeRow | null>(null);
  const [eraseConfirm, setEraseConfirm] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const loadAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const params = new URLSearchParams({
        limit: "26",
        offset: String((page - 1) * 25),
      });
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (accountId) params.set("account_id", accountId);
      const query = `?${params}`;
      const [s, p, st] = await Promise.all([
        apiFetch<SubscriptionRow[]>(`/admin/billing/subscriptions${query}`, {
          token,
        }),
        apiFetch<PendingPurgeRow[]>("/admin/accounts/pending-purge", { token }),
        apiFetch<StripeStatus>("/admin/billing/stripe-status", { token }),
      ]);
      setLoaded(true);
      setSubs(s.slice(0, 25));
      setHasMore(s.length > 25);
      setPending(
        accountId ? p.filter((row) => row.account_id === accountId) : p
      );
      setStripeStatus(st);
    } catch (err) {
      setError(true);
      toast.error(
        err instanceof Error ? err.message : "Impossible de charger les données"
      );
    } finally {
      setLoading(false);
    }
  }, [token, statusFilter, accountId, page]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleExport = async (accountId: string, accountName: string) => {
    if (!token) return;
    if (
      !confirm(
        `Télécharger toutes les données du compte « ${accountName} » au format JSON ?\n\n` +
          `Contenu : profil, utilisateurs, organisations, documents, abonnement, factures, historique des questions.\n\n` +
          `Utilisé pour répondre à une demande RGPD (droit d'accès, article 15).`
      )
    ) {
      return;
    }
    try {
      const data = await apiFetch(`/admin/accounts/${accountId}/export`, {
        token,
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aoria-export-${accountName.replace(/\s+/g, "_")}-${accountId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Données exportées — fichier téléchargé");
    } catch (err) {
      toast.error(
        err instanceof Error && err.message
          ? err.message
          : "Le fichier d'export n'a pas pu être généré. Réessayez dans quelques instants."
      );
    }
  };

  const handleCancelSubscription = async () => {
    if (!token || !cancelTarget) return;
    setActionBusy(true);
    const subscriptionId = cancelTarget.id;
    try {
      const res = await apiFetch<{
        status: string;
        cancel_at_period_end: boolean;
      }>(`/admin/billing/subscriptions/${subscriptionId}/cancel`, {
        token,
        method: "POST",
        body: JSON.stringify({ at_period_end: true }),
      });
      toast.success(
        res.cancel_at_period_end
          ? "Résiliation programmée à la fin de la période"
          : `Subscription résiliée (status: ${res.status})`
      );
      setCancelTarget(null);
      void loadAll();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Échec de la résiliation"
      );
    } finally {
      setActionBusy(false);
    }
  };

  const handleErase = async () => {
    if (!token || !eraseTarget || eraseConfirm !== eraseTarget.account_name)
      return;
    const accountId = eraseTarget.account_id;
    setActionBusy(true);
    try {
      const res = await apiFetch<{ summary: Record<string, number> }>(
        `/admin/accounts/${accountId}/erase`,
        { token, method: "POST" }
      );
      toast.success(`Compte supprimé — ${JSON.stringify(res.summary)}`);
      setEraseTarget(null);
      setEraseConfirm("");
      if (onErased) onErased();
      else void loadAll();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Échec de la suppression"
      );
    } finally {
      setActionBusy(false);
    }
  };

  if (loading && !loaded) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {!accountId && (
        <AdminPageHeader
          section="Pilotage"
          title="Abonnements & paiements"
          description="Suivez les essais, les échéances et les paiements en retard. Ouvrez une fiche client pour gérer ses données."
          actions={
            stripeStatus?.configured ? (
              <Badge variant="outline">
                Stripe{" "}
                {stripeStatus.mode === "live"
                  ? "Production"
                  : stripeStatus.mode === "test"
                    ? "Test"
                    : "Mode inconnu"}
              </Badge>
            ) : undefined
          }
        />
      )}
      {error && <AdminLoadError onRetry={loadAll} />}
      {stripeStatus?.configured && !stripeStatus.webhook_configured && (
        <p
          role="alert"
          className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
        >
          La réception des événements Stripe n’est pas configurée. Les statuts
          de paiement peuvent ne pas être à jour.
        </p>
      )}
      {accountId && lifecycle && (
        <Card className="border shadow-none">
          <CardHeader>
            <CardTitle className="text-base">Données du compte</CardTitle>
            <p className="text-muted-foreground text-sm">
              Téléchargez les données pour répondre à une demande d’accès du
              client.
            </p>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              onClick={() => handleExport(accountId, accountName || "compte")}
            >
              <Download className="size-4" />
              Exporter les données
            </Button>
          </CardContent>
        </Card>
      )}
      {!accountId && !error && pending.length > 0 && (
        <div className="bg-muted/50 rounded-xl border p-4 text-sm">
          <strong>{pending.length} compte(s) en attente de clôture.</strong>
          <p className="text-muted-foreground mt-1">
            Consultez la fiche du client avant l’effacement automatique de ses
            données.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {pending.map((item) => (
              <Button variant="outline" size="sm" asChild key={item.account_id}>
                <Link href={`/admin/clients/${item.account_id}?tab=data`}>
                  {item.account_name}
                </Link>
              </Button>
            ))}
          </div>
        </div>
      )}
      {!lifecycle && !error && (
        <>
          {/* Subscriptions table */}
          <Card className="border shadow-none">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle className="text-base">Abonnements</CardTitle>
                <Select
                  value={statusFilter}
                  disabled={loading}
                  onValueChange={(value) => {
                    setStatusFilter(value);
                    setPage(1);
                  }}
                >
                  <SelectTrigger
                    aria-label="Filtrer les abonnements par statut"
                    className="h-10 w-full sm:w-52"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Tous les statuts</SelectItem>
                    <SelectItem value="active">Actifs</SelectItem>
                    <SelectItem value="trialing">En essai</SelectItem>
                    <SelectItem value="past_due">Retard de paiement</SelectItem>
                    <SelectItem value="canceled">Résiliés</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Compte</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Cycle</TableHead>
                    <TableHead>Statut</TableHead>
                    <TableHead>Échéance</TableHead>
                    <TableHead className="text-right">MRR</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {subs.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={8}
                        className="text-muted-foreground py-8 text-center"
                      >
                        Aucun abonnement.
                      </TableCell>
                    </TableRow>
                  ) : (
                    subs.map((s) => (
                      <TableRow key={s.subscription_id}>
                        <TableCell className="font-medium">
                          <Link
                            className="hover:text-primary hover:underline"
                            href={`/admin/clients/${s.account_id}`}
                          >
                            {s.account_name ?? "—"}
                          </Link>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {s.owner_email ?? "—"}
                        </TableCell>
                        <TableCell>{getPlanLabel(s.plan)}</TableCell>
                        <TableCell>
                          {s.billing_cycle === "monthly" ? "Mensuel" : "Annuel"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={STATUS_COLORS[s.status] ?? "outline"}>
                            {ACCOUNT_STATUS_LABELS[s.status] || s.status}
                          </Badge>
                          {s.cancel_at_period_end && (
                            <Badge variant="destructive" className="ml-2">
                              Résiliation prévue
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {s.current_period_end
                            ? new Date(s.current_period_end).toLocaleDateString(
                                "fr-FR"
                              )
                            : "—"}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {(s.mrr_contribution_cents / 100).toFixed(0)} €
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-2">
                            {(s.status === "active" ||
                              s.status === "trialing" ||
                              s.status === "past_due") && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() =>
                                  setCancelTarget({
                                    id: s.subscription_id,
                                    email: s.owner_email,
                                  })
                                }
                                disabled={
                                  s.cancel_at_period_end ||
                                  loading ||
                                  actionBusy
                                }
                              >
                                <XCircle className="mr-1 h-3.5 w-3.5" />
                                Résilier
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-muted-foreground text-sm" role="status">
              Page {page} · {subs.length} abonnement(s) affiché(s)
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1 || loading}
                onClick={() => setPage((value) => value - 1)}
              >
                Précédent
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasMore || loading}
                onClick={() => setPage((value) => value + 1)}
              >
                Suivant
              </Button>
            </div>
          </div>
        </>
      )}
      {accountId && lifecycle && !error && (
        <>
          {/* Pending purge */}
          <Card className="border shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Trash2 className="h-4 w-4" />
                Comptes à clôturer
                {pending.length > 0 && (
                  <Badge variant="destructive">{pending.length}</Badge>
                )}
              </CardTitle>
              <p className="text-muted-foreground text-sm">
                Comptes inactifs depuis trop longtemps (essai non transformé,
                abonnement résilié, paiement non régularisé). Une suppression
                automatique est planifiée chaque jour à 12h (heure de Paris).
                Avant suppression, vous pouvez&nbsp;:
              </p>
              <ul className="text-muted-foreground mt-2 list-disc space-y-1 pl-5 text-sm">
                <li>
                  <strong>Exporter les données</strong> — télécharge un fichier
                  JSON avec toutes les infos du compte (pour répondre à une
                  demande RGPD d&apos;accès).
                </li>
                <li>
                  <strong>Supprimer maintenant</strong> — efface définitivement
                  le compte sans attendre le cron (utile pour une demande RGPD
                  d&apos;effacement).
                </li>
              </ul>
            </CardHeader>
            <CardContent>
              {pending.length === 0 ? (
                <p className="text-muted-foreground py-4 text-center text-sm">
                  Aucun compte en attente de purge.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Compte</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Raison</TableHead>
                      <TableHead>Éligible depuis</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pending.map((p) => (
                      <TableRow key={p.account_id}>
                        <TableCell className="font-medium">
                          {p.account_name}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {p.owner_email}
                        </TableCell>
                        <TableCell>
                          {REASON_LABELS[p.reason] ?? p.reason}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {new Date(p.eligible_since).toLocaleDateString(
                            "fr-FR"
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              handleExport(p.account_id, p.account_name)
                            }
                            className="mr-2"
                            title="Télécharger toutes les données au format JSON"
                          >
                            <Download className="mr-1 h-3.5 w-3.5" />
                            Exporter les données
                          </Button>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => setEraseTarget(p)}
                            title="Effacer définitivement ce compte"
                          >
                            <Trash2 className="mr-1 h-3.5 w-3.5" />
                            Supprimer maintenant
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
      <Dialog
        open={cancelTarget !== null}
        onOpenChange={(open) => {
          if (!open && !actionBusy) setCancelTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Programmer la résiliation</DialogTitle>
            <DialogDescription>
              L’abonnement de {cancelTarget?.email || "ce client"} sera résilié
              à la fin de la période en cours. Le client conserve son accès
              jusqu’à l’échéance.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              disabled={actionBusy}
              onClick={() => setCancelTarget(null)}
            >
              Conserver l’abonnement
            </Button>
            <Button
              variant="destructive"
              disabled={actionBusy}
              onClick={handleCancelSubscription}
            >
              {actionBusy ? "Enregistrement…" : "Résilier à l’échéance"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={eraseTarget !== null}
        onOpenChange={(open) => {
          if (!open && !actionBusy) {
            setEraseTarget(null);
            setEraseConfirm("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer définitivement le compte</DialogTitle>
            <DialogDescription>
              Les utilisateurs, organisations, documents, conversations et
              données d’abonnement du compte seront effacés. Cette action est
              irréversible. Exportez les données au préalable si nécessaire.
            </DialogDescription>
          </DialogHeader>
          <label htmlFor="erase-account-confirm" className="text-sm">
            Saisissez <strong>{eraseTarget?.account_name}</strong> pour
            confirmer.
          </label>
          <Input
            id="erase-account-confirm"
            value={eraseConfirm}
            onChange={(e) => setEraseConfirm(e.target.value)}
            autoComplete="off"
          />
          <DialogFooter>
            <Button
              variant="outline"
              disabled={actionBusy}
              onClick={() => {
                setEraseTarget(null);
                setEraseConfirm("");
              }}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              disabled={
                actionBusy ||
                !eraseTarget ||
                eraseConfirm !== eraseTarget.account_name
              }
              onClick={handleErase}
            >
              {actionBusy ? "Suppression…" : "Supprimer définitivement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
