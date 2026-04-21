"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  DollarSign,
  TrendingUp,
  Users,
  AlertTriangle,
  Trash2,
  Download,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
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
import { PLAN_LABELS } from "@/lib/billing-api";

type BillingMetrics = {
  mrr_eur: number;
  arr_eur: number;
  active_subscriptions: number;
  subscriptions_by_plan: Record<string, number>;
  trial_active: number;
  accounts_suspended: number;
  accounts_canceled: number;
  new_subscriptions_30d: number;
  cancellations_30d: number;
  monthly_churn_pct: number;
};

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

const STATUS_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  trialing: "secondary",
  past_due: "outline",
  canceled: "destructive",
  unpaid: "destructive",
};

const REASON_LABELS: Record<string, string> = {
  trial_expired: "Essai expiré (>30 j)",
  canceled: "Résiliation (>30 j)",
  unpaid: "Impayé (>60 j)",
};

export default function AdminBillingPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [metrics, setMetrics] = useState<BillingMetrics | null>(null);
  const [subs, setSubs] = useState<SubscriptionRow[]>([]);
  const [pending, setPending] = useState<PendingPurgeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const loadAll = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const query = statusFilter === "all" ? "" : `?status=${statusFilter}`;
      const [m, s, p] = await Promise.all([
        apiFetch<BillingMetrics>("/admin/billing/metrics", { token }),
        apiFetch<SubscriptionRow[]>(`/admin/billing/subscriptions${query}`, { token }),
        apiFetch<PendingPurgeRow[]>("/admin/accounts/pending-purge", { token }),
      ]);
      setMetrics(m);
      setSubs(s);
      setPending(p);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de charger les données");
    } finally {
      setLoading(false);
    }
  }, [token, statusFilter]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleExport = async (accountId: string, accountName: string) => {
    if (!token) return;
    try {
      const data = await apiFetch(`/admin/accounts/${accountId}/export`, { token });
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aoria-export-${accountName.replace(/\s+/g, "_")}-${accountId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Export téléchargé");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Échec de l'export");
    }
  };

  const handleCancelSubscription = async (
    subscriptionId: string,
    ownerEmail: string | null,
  ) => {
    if (!token) return;
    const mode = confirm(
      `Résilier l'abonnement de ${ownerEmail ?? "ce compte"} ?\n\n` +
        `OK  = résilier à la fin de la période (recommandé, le client garde son accès jusqu'à l'échéance)\n` +
        `Annuler = ne rien faire\n\n` +
        `Pour une résiliation immédiate sans accès restant, fais-le depuis le dashboard Stripe.`,
    );
    if (!mode) return;
    try {
      const res = await apiFetch<{ status: string; cancel_at_period_end: boolean }>(
        `/admin/billing/subscriptions/${subscriptionId}/cancel`,
        {
          token,
          method: "POST",
          body: JSON.stringify({ at_period_end: true }),
        },
      );
      toast.success(
        res.cancel_at_period_end
          ? "Résiliation programmée à la fin de la période"
          : `Subscription résiliée (status: ${res.status})`,
      );
      loadAll();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Échec de la résiliation");
    }
  };

  const handleErase = async (accountId: string, ownerEmail: string) => {
    if (!token) return;
    if (
      !confirm(
        `Supprimer définitivement le compte ${ownerEmail} ?\n\nCette action est irréversible et supprime toutes les données (documents, conversations, abonnements). Les fichiers MinIO et les vecteurs Qdrant seront aussi effacés.`,
      )
    ) {
      return;
    }
    try {
      const res = await apiFetch<{ summary: Record<string, number> }>(
        `/admin/accounts/${accountId}/erase`,
        { token, method: "POST" },
      );
      toast.success(`Compte supprimé — ${JSON.stringify(res.summary)}`);
      loadAll();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Échec de la suppression");
    }
  };

  if (loading && !metrics) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Facturation & abonnements</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Vue d&apos;ensemble des revenus récurrents, du pipeline d&apos;essais et de la rétention RGPD.
        </p>
      </div>

      {/* KPI cards */}
      {metrics && (
        <div className="grid gap-4 md:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <DollarSign className="h-3.5 w-3.5" />
                MRR
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">
                {metrics.mrr_eur.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} €
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                ARR ≈ {metrics.arr_eur.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} €
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <TrendingUp className="h-3.5 w-3.5" />
                Abonnements actifs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">{metrics.active_subscriptions}</p>
              <p className="text-xs text-muted-foreground mt-1">
                Solo {metrics.subscriptions_by_plan.solo ?? 0} · Équipe {metrics.subscriptions_by_plan.equipe ?? 0} · Groupe {metrics.subscriptions_by_plan.groupe ?? 0}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5" />
                Essais actifs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">{metrics.trial_active}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics.new_subscriptions_30d} conversions sur 30 j
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5" />
                Churn (30 j)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold tabular-nums">{metrics.monthly_churn_pct} %</p>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics.cancellations_30d} résiliations · {metrics.accounts_suspended} suspendus
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Subscriptions table */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Abonnements</CardTitle>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-8 rounded-md border bg-background px-2 text-sm"
            >
              <option value="all">Tous</option>
              <option value="active">Actifs</option>
              <option value="trialing">En essai</option>
              <option value="past_due">Retard de paiement</option>
              <option value="canceled">Résiliés</option>
            </select>
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
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    Aucun abonnement.
                  </TableCell>
                </TableRow>
              ) : (
                subs.map((s) => (
                  <TableRow key={s.subscription_id}>
                    <TableCell className="font-medium">{s.account_name ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{s.owner_email ?? "—"}</TableCell>
                    <TableCell>{PLAN_LABELS[s.plan] ?? s.plan}</TableCell>
                    <TableCell>{s.billing_cycle === "monthly" ? "Mensuel" : "Annuel"}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_COLORS[s.status] ?? "outline"}>{s.status}</Badge>
                      {s.cancel_at_period_end && (
                        <Badge variant="outline" className="ml-2">Résiliation prévue</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {s.current_period_end
                        ? new Date(s.current_period_end).toLocaleDateString("fr-FR")
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {(s.mrr_contribution_cents / 100).toFixed(0)} €
                    </TableCell>
                    <TableCell className="text-right">
                      {s.status === "active" || s.status === "trialing" || s.status === "past_due" ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleCancelSubscription(s.subscription_id, s.owner_email)}
                          disabled={s.cancel_at_period_end}
                        >
                          <XCircle className="h-3.5 w-3.5 mr-1" />
                          Résilier
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Pending purge */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Trash2 className="h-4 w-4" />
            Comptes à purger
            {pending.length > 0 && (
              <Badge variant="destructive">{pending.length}</Badge>
            )}
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            Comptes ayant dépassé leur fenêtre de rétention RGPD. Le cron les supprimera à 10h UTC.
            Vous pouvez aussi agir manuellement (export RGPD ou suppression immédiate).
          </p>
        </CardHeader>
        <CardContent>
          {pending.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
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
                    <TableCell className="font-medium">{p.account_name}</TableCell>
                    <TableCell className="text-muted-foreground">{p.owner_email}</TableCell>
                    <TableCell>{REASON_LABELS[p.reason] ?? p.reason}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(p.eligible_since).toLocaleDateString("fr-FR")}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleExport(p.account_id, p.account_name)}
                        className="mr-2"
                      >
                        <Download className="h-3.5 w-3.5 mr-1" />
                        Export
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => handleErase(p.account_id, p.owner_email)}
                      >
                        <Trash2 className="h-3.5 w-3.5 mr-1" />
                        Supprimer
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
