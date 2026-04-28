"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, ExternalLink, Zap, Check, CreditCard, FileText, Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  fetchQuota,
  fetchSubscription,
  fetchUsageSummary,
  fetchAddons,
  addAddon,
  removeAddon,
  openCustomerPortal,
  startBoosterCheckout,
  startCheckout,
  changePlan,
  previewChangePlan,
  reactivateSubscription,
  cancelSubscription,
  fetchInvoices,
  startPaymentMethodUpdate,
  ADDON_LABELS,
  type ChangePlanPreview,
  type QuotaInfo,
  type SubscriptionInfo,
  type UsageSummary,
  type ActiveAddon,
  type AddonType,
  type InvoiceRow,
} from "@/lib/billing-api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  PLANS,
  COMMERCIAL_PLANS,
  getPlanLabel,
  type BillingCycle,
  type PlanCode,
} from "@/lib/plans";

function UsageRow({
  label,
  used,
  limit,
  indent = false,
}: {
  label: string;
  used: number;
  limit: number;
  indent?: boolean;
}) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const color =
    pct >= 100 ? "bg-destructive"
      : pct >= 80 ? "bg-orange-500"
      : "bg-primary";
  return (
    <div className={indent ? "pl-4" : ""}>
      <div className="flex items-center justify-between text-sm mb-1">
        <span className={indent ? "text-muted-foreground text-xs" : ""}>{label}</span>
        <span className="tabular-nums font-medium">
          {used} / {limit}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full transition-all ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}


export default function BillingPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [addons, setAddons] = useState<ActiveAddon[]>([]);
  const [invoices, setInvoices] = useState<InvoiceRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [cycle, setCycle] = useState<BillingCycle>("monthly");
  const [busy, setBusy] = useState(false);

  // Change-plan confirmation dialog (with prorata preview)
  const [changePlanTarget, setChangePlanTarget] = useState<{
    plan: PlanCode;
    cycle: BillingCycle;
  } | null>(null);
  const [changePlanPreview, setChangePlanPreview] = useState<ChangePlanPreview | null>(null);
  const [changePlanLoading, setChangePlanLoading] = useState(false);
  const [changePlanError, setChangePlanError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [q, s, u, a, inv] = await Promise.all([
        fetchQuota(token),
        fetchSubscription(token),
        fetchUsageSummary(token),
        fetchAddons(token).catch(() => [] as ActiveAddon[]),
        fetchInvoices(token).catch(() => [] as InvoiceRow[]),
      ]);
      setQuota(q);
      setSubscription(s);
      setUsage(u);
      setAddons(a);
      setInvoices(inv);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de charger l'abonnement");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Refresh when the user creates or deletes something in another page
  useEffect(() => {
    const handler = () => loadData();
    window.addEventListener("quota-updated", handler);
    return () => window.removeEventListener("quota-updated", handler);
  }, [loadData]);

  const hasCommercialSub =
    !!subscription &&
    ["solo", "equipe", "groupe"].includes(subscription.plan) &&
    ["active", "trialing", "past_due"].includes(subscription.status);

  const handleCheckout = async (plan: PlanCode) => {
    if (!token) return;
    if (hasCommercialSub) {
      // Open the confirmation dialog and fetch the prorata preview so the
      // user sees the exact amount before confirming the change.
      setChangePlanTarget({ plan, cycle });
      setChangePlanPreview(null);
      setChangePlanError(null);
      setChangePlanLoading(true);
      try {
        const preview = await previewChangePlan(token, plan, cycle);
        setChangePlanPreview(preview);
      } catch (err) {
        setChangePlanError(
          err instanceof Error
            ? err.message
            : "Impossible de calculer l'aperçu du montant.",
        );
      } finally {
        setChangePlanLoading(false);
      }
      return;
    }
    setBusy(true);
    try {
      const { checkout_url } = await startCheckout(token, plan, cycle);
      if (!checkout_url) {
        throw new Error(
          "La page de paiement Stripe n'a pas pu être générée. Réessayez dans quelques instants.",
        );
      }
      window.location.href = checkout_url;
      setTimeout(() => setBusy(false), 5000);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du changement de plan");
      setBusy(false);
    }
  };

  const confirmChangePlan = async () => {
    if (!token || !changePlanTarget) return;
    setBusy(true);
    try {
      await changePlan(token, changePlanTarget.plan, changePlanTarget.cycle);
      toast.success("Plan mis à jour. Le prorata a été appliqué.");
      setChangePlanTarget(null);
      setChangePlanPreview(null);
      await loadData();
      // Refresh the plan badge rendered by the sidebar so the UI is
      // consistent across the shell without a full page reload.
      window.dispatchEvent(new Event("plan-updated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du changement de plan");
    } finally {
      setBusy(false);
    }
  };

  const handleReactivate = async () => {
    if (!token) return;
    setBusy(true);
    try {
      await reactivateSubscription(token);
      toast.success("Abonnement réactivé.");
      await loadData();
      window.dispatchEvent(new Event("plan-updated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de réactiver l'abonnement");
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!token) return;
    if (
      !confirm(
        "Résilier votre abonnement AORIA RH ?\n\n" +
          "Vous conservez un accès complet jusqu'à la fin de la période en cours. " +
          "Au-delà, vos données sont conservées 30 jours avant suppression définitive. " +
          "Vous pouvez réactiver votre abonnement à tout moment avant la date de fin.",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await cancelSubscription(token);
      toast.success("Résiliation programmée. Un email de confirmation vous a été envoyé.");
      await loadData();
      window.dispatchEvent(new Event("plan-updated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de résilier l'abonnement");
    } finally {
      setBusy(false);
    }
  };

  const handleUpdateCard = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const { checkout_url } = await startPaymentMethodUpdate(token);
      if (!checkout_url) {
        throw new Error(
          "La page Stripe de mise à jour de la carte n'a pas pu être générée. Réessayez dans quelques instants.",
        );
      }
      window.location.href = checkout_url;
      setTimeout(() => setBusy(false), 5000);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Impossible d'ouvrir la mise à jour de la carte",
      );
      setBusy(false);
    }
  };

  const handlePortal = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const { portal_url } = await openCustomerPortal(token);
      if (!portal_url) {
        throw new Error(
          "L'espace de gestion Stripe n'a pas pu être ouvert. Réessayez dans quelques instants.",
        );
      }
      window.location.href = portal_url;
      // Safety net: if the browser blocks the redirect or the URL is
      // malformed without throwing, restore the button after 5 s so the
      // user can retry instead of staring at a spinner forever.
      setTimeout(() => setBusy(false), 5000);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible d'ouvrir l'espace client");
      setBusy(false);
    }
  };

  const handleAddAddon = async (addon_type: AddonType) => {
    if (!token) return;
    setBusy(true);
    try {
      await addAddon(token, addon_type);
      toast.success(`${ADDON_LABELS[addon_type]} ajouté`);
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible d'ajouter l'add-on");
    } finally {
      setBusy(false);
    }
  };

  const handleRemoveAddon = async (addon: ActiveAddon) => {
    if (!token) return;
    if (!confirm(`Retirer ${ADDON_LABELS[addon.addon_type]} de votre abonnement ?`)) return;
    setBusy(true);
    try {
      await removeAddon(token, addon.id);
      toast.success("Add-on retiré");
      await loadData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de retirer l'add-on");
    } finally {
      setBusy(false);
    }
  };

  const handleBooster = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const { checkout_url } = await startBoosterCheckout(token);
      if (!checkout_url) {
        throw new Error(
          "La page de paiement Stripe n'a pas pu être générée. Réessayez dans quelques instants.",
        );
      }
      window.location.href = checkout_url;
      setTimeout(() => setBusy(false), 5000);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible d'acheter le pack booster");
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const isCommercial = quota && ["solo", "equipe", "groupe"].includes(quota.plan);
  const quotaPct = quota && quota.quota > 0 ? Math.min(100, Math.round((quota.used / quota.quota) * 100)) : 0;
  const quotaBarClass =
    quota?.quota_status === "hard_warning"
      ? "bg-destructive"
      : quota?.quota_status === "soft_warning"
        ? "bg-orange-500"
        : "bg-primary";

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Abonnement & facturation</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gérez votre plan, votre consommation et vos factures.
        </p>
      </div>

      {/* Current plan + quota */}
      {quota && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  Plan actuel
                  <Badge variant={quota.status === "active" ? "default" : "secondary"}>
                    {getPlanLabel(quota.plan)}
                  </Badge>
                  {subscription?.cancel_at_period_end ? (
                    <Badge variant="destructive">Résilié</Badge>
                  ) : quota.status !== "active" && (
                    <Badge variant="outline">{quota.status}</Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  {quota.trial_ends_at ? (
                    <>Essai se termine le {new Date(quota.trial_ends_at).toLocaleDateString("fr-FR")}</>
                  ) : subscription?.current_period_end ? (
                    subscription.cancel_at_period_end ? (
                      <>
                        Accès maintenu jusqu&apos;au{" "}
                        {new Date(subscription.current_period_end).toLocaleDateString("fr-FR")}
                      </>
                    ) : (
                      <>
                        Prochaine échéance le{" "}
                        {new Date(subscription.current_period_end).toLocaleDateString("fr-FR")}
                      </>
                    )
                  ) : (
                    <>Plan interne — non facturé</>
                  )}
                </CardDescription>
              </div>
              {isCommercial && (
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={handleUpdateCard} disabled={busy}>
                    <CreditCard className="mr-2 h-4 w-4" />
                    Modifier ma carte
                  </Button>
                  <Button variant="outline" size="sm" onClick={handlePortal} disabled={busy}>
                    <ExternalLink className="mr-2 h-4 w-4" />
                    Portail Stripe
                  </Button>
                  {!subscription?.cancel_at_period_end && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleCancel}
                      disabled={busy}
                      className="text-destructive hover:text-destructive"
                    >
                      Résilier
                    </Button>
                  )}
                </div>
              )}
            </div>
            {subscription?.cancel_at_period_end && subscription.current_period_end && (
              <div className="mt-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
                <p className="font-medium">Votre abonnement AORIA RH est résilié.</p>
                <p className="text-muted-foreground mt-1">
                  Vous gardez un accès complet jusqu&apos;au{" "}
                  <strong>{new Date(subscription.current_period_end).toLocaleDateString("fr-FR")}</strong>.
                  Au-delà, vos données sont conservées 30 jours avant suppression définitive (RGPD).
                </p>
                <div className="mt-3">
                  <Button size="sm" onClick={handleReactivate} disabled={busy}>
                    {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                    Réactiver mon abonnement
                  </Button>
                </div>
              </div>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2 text-sm">
                <span className="text-muted-foreground">
                  Questions ce mois-ci
                </span>
                <span className="font-medium tabular-nums">
                  {quota.used} / {quota.quota}
                  {quota.booster_remaining > 0 && (
                    <span className="text-muted-foreground"> · +{quota.booster_remaining} booster</span>
                  )}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                <div
                  className={`h-full transition-all ${quotaBarClass}`}
                  style={{ width: `${quotaPct}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                Période du {new Date(quota.period_start).toLocaleDateString("fr-FR")}
                {" "}au {new Date(quota.period_end).toLocaleDateString("fr-FR")}
              </p>
            </div>
            <div className="flex justify-end">
              <Button onClick={handleBooster} disabled={busy}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Zap className="mr-2 h-4 w-4" />}
                Acheter un pack booster (+500 questions, 25 €)
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Usage overview (users / orgs / docs / questions) */}
      {usage && (
        <Card>
          <CardHeader>
            <CardTitle>Utilisation</CardTitle>
            <CardDescription>
              Consommation actuelle de vos limites. Mise à jour en temps réel à chaque
              création ou question posée.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <UsageRow
              label="Utilisateurs"
              used={usage.users.used}
              limit={usage.users.limit}
            />
            <UsageRow
              label="Organisations"
              used={usage.organisations.used}
              limit={usage.organisations.limit}
            />
            {usage.documents_by_org.length > 0 && (
              <div className="space-y-2 pt-1">
                <p className="text-xs text-muted-foreground">Documents par organisation</p>
                {usage.documents_by_org.map((d) => (
                  <UsageRow
                    key={d.org_id}
                    label={d.org_name}
                    used={d.used}
                    limit={d.limit}
                    indent
                  />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Add-ons — self-service */}
      {isCommercial && (
        <Card>
          <CardHeader>
            <CardTitle>Add-ons</CardTitle>
            <CardDescription>
              Ajustez finement votre abonnement sans changer de plan. Facturés au prorata
              jusqu&apos;à la prochaine échéance.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => handleAddAddon("extra_user")}
              >
                +1 utilisateur · 15 €/mois
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => handleAddAddon("extra_org")}
              >
                +1 organisation · 19 €/mois
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => handleAddAddon("extra_docs")}
              >
                +500 documents · 10 €/mois
              </Button>
              <Button
                disabled={busy}
                onClick={handleBooster}
                className="border-2 border-primary"
              >
                <Zap className="mr-2 h-4 w-4" />
                Pack booster · +500 questions · 25 €
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              <strong>Pack booster</strong> : achat unique, sans expiration. Consommé après épuisement du quota mensuel.
            </p>

            {addons.length > 0 && (
              <div className="border-t pt-4 space-y-2">
                <p className="text-xs text-muted-foreground">Add-ons actifs</p>
                {addons.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between text-sm py-1"
                  >
                    <span>
                      <strong>{a.quantity}×</strong> {ADDON_LABELS[a.addon_type]}
                      <span className="text-muted-foreground ml-2">
                        ({((a.unit_price_cents * a.quantity) / 100).toFixed(0)} €/mois)
                      </span>
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveAddon(a)}
                      disabled={busy}
                    >
                      Retirer
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Plan catalog (upgrade / change plan) */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Nos offres</h2>
          <div className="flex items-center gap-1 rounded-lg border p-1 bg-muted/30">
            <button
              onClick={() => setCycle("monthly")}
              className={`px-3 py-1 text-sm rounded-md transition ${
                cycle === "monthly" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Mensuel
            </button>
            <button
              onClick={() => setCycle("yearly")}
              className={`px-3 py-1 text-sm rounded-md transition ${
                cycle === "yearly" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Annuel
              <span className="ml-1 text-xs text-primary">(-2 mois)</span>
            </button>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {COMMERCIAL_PLANS.map((code) => {
            const plan = PLANS[code];
            const price = cycle === "monthly" ? plan.priceMonthly : plan.priceYearly;
            const isCurrent = quota?.plan === code;
            const featured = plan.featured === true;
            return (
              <Card
                key={code}
                className={`relative ${featured ? "border-primary shadow-md" : ""}`}
              >
                {featured && (
                  <Badge className="absolute -top-2 left-1/2 -translate-x-1/2">
                    Le plus choisi
                  </Badge>
                )}
                <CardHeader>
                  <CardTitle>{plan.label}</CardTitle>
                  <CardDescription className="min-h-[40px]">
                    {plan.target}
                  </CardDescription>
                  <div className="flex items-baseline gap-1 pt-2">
                    <span className="text-3xl font-bold">{price} €</span>
                    <span className="text-sm text-muted-foreground">
                      /{cycle === "monthly" ? "mois" : "an"}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <ul className="space-y-2 text-sm">
                    {plan.features.map((f) => (
                      <li key={f} className="flex gap-2">
                        <Check className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>
                  <Button
                    className="w-full"
                    variant={isCurrent ? "outline" : featured ? "default" : "outline"}
                    disabled={busy || isCurrent}
                    onClick={() => handleCheckout(code)}
                  >
                    {isCurrent
                      ? "Plan actuel"
                      : hasCommercialSub
                        ? `Passer à ${plan.label}`
                        : `Souscrire ${plan.label}`}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Invoices history */}
      {invoices.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Historique des factures
            </CardTitle>
            <CardDescription>
              Les {invoices.length < 24 ? invoices.length : "24"} dernières factures et reçus Stripe. Cliquez sur une ligne pour télécharger le PDF.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="divide-y">
              {invoices.map((inv) => {
                const amount = ((inv.status === "paid" ? inv.amount_paid_cents : inv.amount_due_cents) / 100).toLocaleString("fr-FR", {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                });
                const currency = (inv.currency || "eur").toUpperCase();
                const statusBadge = inv.status === "paid" ? (
                  <Badge variant="default">Payée</Badge>
                ) : inv.status === "open" ? (
                  <Badge variant="outline">En attente</Badge>
                ) : inv.status === "void" ? (
                  <Badge variant="secondary">Annulée</Badge>
                ) : inv.status === "uncollectible" ? (
                  <Badge variant="destructive">Impayée</Badge>
                ) : (
                  <Badge variant="outline">{inv.status ?? "—"}</Badge>
                );
                return (
                  <div
                    key={inv.id}
                    className="flex items-center justify-between py-3 gap-4 text-sm"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="tabular-nums text-muted-foreground shrink-0">
                        {inv.created ? new Date(inv.created * 1000).toLocaleDateString("fr-FR") : "—"}
                      </span>
                      <span className="font-medium truncate">
                        {inv.number ?? inv.id}
                      </span>
                      {statusBadge}
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="tabular-nums font-medium">
                        {amount} {currency}
                      </span>
                      {inv.invoice_pdf && (
                        <a
                          href={inv.invoice_pdf}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline flex items-center gap-1"
                          title="Télécharger le PDF"
                        >
                          <Download className="h-3.5 w-3.5" />
                          PDF
                        </a>
                      )}
                      {inv.hosted_invoice_url && (
                        <a
                          href={inv.hosted_invoice_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-muted-foreground hover:text-foreground hover:underline"
                          title="Voir la facture sur Stripe"
                        >
                          Voir
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-muted-foreground text-center">
        Tarifs hors taxes. Résiliable à tout moment depuis votre espace de gestion.
        {" "}
        <a href="/cgv" className="underline hover:text-foreground" target="_blank">CGV</a>
        {" · "}
        <a href="/politique-confidentialite" className="underline hover:text-foreground" target="_blank">
          Politique de confidentialité
        </a>
      </p>

      <Dialog
        open={changePlanTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setChangePlanTarget(null);
            setChangePlanPreview(null);
            setChangePlanError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Passer au plan{" "}
              {changePlanTarget ? PLANS[changePlanTarget.plan].label : ""}
              {changePlanTarget?.cycle === "yearly" ? " (annuel)" : " (mensuel)"}
            </DialogTitle>
            <DialogDescription>
              Stripe appliquera un prorata sur la période en cours.
            </DialogDescription>
          </DialogHeader>
          <div className="text-sm space-y-2 py-1">
            {changePlanLoading && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Calcul du montant en cours…
              </div>
            )}
            {changePlanError && (
              <p className="text-destructive">{changePlanError}</p>
            )}
            {changePlanPreview && (
              <div className="rounded-lg border bg-muted/30 p-3 space-y-1 tabular-nums">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">
                    Montant dû à la prochaine facture
                  </span>
                  <strong>
                    {changePlanPreview.amount_due_eur.toLocaleString("fr-FR", {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}{" "}
                    € TTC
                  </strong>
                </div>
                {changePlanPreview.amount_tax_cents > 0 && (
                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>dont TVA</span>
                    <span>
                      {(changePlanPreview.amount_tax_cents / 100).toLocaleString("fr-FR", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })}{" "}
                      €
                    </span>
                  </div>
                )}
                {changePlanPreview.amount_due_cents < 0 && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Un crédit sera appliqué sur votre prochaine facture (montant négatif).
                  </p>
                )}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setChangePlanTarget(null);
                setChangePlanPreview(null);
                setChangePlanError(null);
              }}
              disabled={busy}
            >
              Annuler
            </Button>
            <Button
              onClick={confirmChangePlan}
              disabled={busy || changePlanLoading || !!changePlanError}
            >
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Confirmer le changement
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
