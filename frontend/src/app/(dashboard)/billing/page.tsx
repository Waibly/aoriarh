"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, ExternalLink, Zap, Check } from "lucide-react";
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
  ADDON_LABELS,
  PLANS_CATALOG,
  PLAN_LABELS,
  type BillingCycle,
  type PlanCode,
  type QuotaInfo,
  type SubscriptionInfo,
  type UsageSummary,
  type ActiveAddon,
  type AddonType,
} from "@/lib/billing-api";

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
  const [loading, setLoading] = useState(true);
  const [cycle, setCycle] = useState<BillingCycle>("monthly");
  const [busy, setBusy] = useState(false);

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [q, s, u, a] = await Promise.all([
        fetchQuota(token),
        fetchSubscription(token),
        fetchUsageSummary(token),
        fetchAddons(token).catch(() => [] as ActiveAddon[]),
      ]);
      setQuota(q);
      setSubscription(s);
      setUsage(u);
      setAddons(a);
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
    setBusy(true);
    try {
      if (hasCommercialSub) {
        const cycleChanged = subscription?.billing_cycle !== cycle;
        const planChanged = subscription?.plan !== plan;
        const label = planChanged
          ? `Passer au plan ${PLANS_CATALOG[plan].name}${cycleChanged ? ` (${cycle === "yearly" ? "annuel" : "mensuel"})` : ""} ?\n\nLa différence sera facturée au prorata (ou créditée si downgrade).`
          : `Changer le cycle en ${cycle === "yearly" ? "annuel" : "mensuel"} ?`;
        if (!confirm(label)) {
          setBusy(false);
          return;
        }
        await changePlan(token, plan, cycle);
        toast.success("Plan mis à jour. Le prorata a été appliqué.");
        await loadData();
        setBusy(false);
      } else {
        const { checkout_url } = await startCheckout(token, plan, cycle);
        window.location.href = checkout_url;
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du changement de plan");
      setBusy(false);
    }
  };

  const handlePortal = async () => {
    if (!token) return;
    setBusy(true);
    try {
      const { portal_url } = await openCustomerPortal(token);
      window.location.href = portal_url;
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
      window.location.href = checkout_url;
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
                    {PLAN_LABELS[quota.plan] ?? quota.plan}
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
                <Button variant="outline" onClick={handlePortal} disabled={busy}>
                  {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <ExternalLink className="mr-2 h-4 w-4" />}
                  Gérer mon abonnement
                </Button>
              )}
            </div>
            {subscription?.cancel_at_period_end && subscription.current_period_end && (
              <div className="mt-3 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
                <p className="font-medium">Votre abonnement AORIA RH est résilié.</p>
                <p className="text-muted-foreground mt-1">
                  Vous gardez un accès complet jusqu&apos;au{" "}
                  <strong>{new Date(subscription.current_period_end).toLocaleDateString("fr-FR")}</strong>.
                  Au-delà, vos données sont conservées 30 jours avant suppression définitive (RGPD).
                  Vous pouvez reprendre votre abonnement à tout moment depuis &laquo; Gérer mon abonnement &raquo;.
                </p>
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
              <Button variant="outline" size="sm" onClick={handleBooster} disabled={busy}>
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
            <div className="grid gap-3 md:grid-cols-3">
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
            </div>

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
          {(Object.entries(PLANS_CATALOG) as [PlanCode, typeof PLANS_CATALOG[PlanCode]][]).map(
            ([code, plan]) => {
              const price = cycle === "monthly" ? plan.priceMonthly : plan.priceYearly;
              const isCurrent = quota?.plan === code;
              const featured = "featured" in plan && plan.featured;
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
                    <CardTitle>{plan.name}</CardTitle>
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
                          ? `Passer à ${plan.name}`
                          : `Souscrire ${plan.name}`}
                    </Button>
                  </CardContent>
                </Card>
              );
            },
          )}
        </div>
      </div>

      <p className="text-xs text-muted-foreground text-center">
        Tarifs hors taxes. Résiliable à tout moment depuis votre espace de gestion.
        {" "}
        <a href="/cgv" className="underline hover:text-foreground" target="_blank">CGV</a>
        {" · "}
        <a href="/politique-confidentialite" className="underline hover:text-foreground" target="_blank">
          Politique de confidentialité
        </a>
      </p>
    </div>
  );
}
