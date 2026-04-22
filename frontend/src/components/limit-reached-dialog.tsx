"use client";

import { useRouter } from "next/navigation";
import { ArrowUpRight, Plus, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PLANS, type PlanCode } from "@/lib/plans";

/**
 * Affiché quand une action est bloquée par la limite du plan.
 *
 * Présente deux options côte à côte :
 *  - Ajouter un add-on ponctuel (si plan commercial ET quota add-on non épuisé)
 *  - Passer à l'offre supérieure (si elle existe)
 *
 * Le choix final reste toujours à l'utilisateur — pas d'auto-upsell.
 */

export type LimitResource = "organisation" | "user" | "document";

const RESOURCE_META: Record<
  LimitResource,
  { label: string; labelPlural: string; addonType: string; addonPriceEur: number; addonUnit: string }
> = {
  organisation: {
    label: "organisation",
    labelPlural: "organisations",
    addonType: "extra_org",
    addonPriceEur: 19,
    addonUnit: "+1 organisation",
  },
  user: {
    label: "utilisateur",
    labelPlural: "utilisateurs",
    addonType: "extra_user",
    addonPriceEur: 15,
    addonUnit: "+1 utilisateur",
  },
  document: {
    label: "document",
    labelPlural: "documents",
    addonType: "extra_docs",
    addonPriceEur: 10,
    addonUnit: "+500 documents",
  },
};

const NEXT_PLAN: Partial<Record<PlanCode, PlanCode>> = {
  solo: "equipe",
  equipe: "groupe",
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  resource: LimitResource;
  currentPlan: string;
  includedCount: number;
  usedCount: number;
  /** Nb d'add-ons déjà actifs sur cette ressource (quantity totale). */
  activeAddonCount?: number;
  /** Plafond d'add-ons pour la ressource (3 pour user, illimité autres). */
  addonCap?: number;
}

export function LimitReachedDialog({
  open,
  onOpenChange,
  resource,
  currentPlan,
  includedCount,
  usedCount,
  activeAddonCount = 0,
  addonCap,
}: Props) {
  const router = useRouter();
  const meta = RESOURCE_META[resource];
  const planLabel =
    currentPlan in PLANS ? PLANS[currentPlan as keyof typeof PLANS].label : currentPlan;

  const isCommercial = ["solo", "equipe", "groupe"].includes(currentPlan);
  const addonAvailable =
    isCommercial && (addonCap == null || activeAddonCount < addonCap);

  const nextPlan = NEXT_PLAN[currentPlan as PlanCode];
  const nextPlanMeta = nextPlan ? PLANS[nextPlan] : null;

  const goToBilling = (anchor: "addons" | "plans") => {
    router.push(`/billing#${anchor}`);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Limite atteinte</DialogTitle>
          <DialogDescription>
            Vous utilisez <strong>{usedCount}</strong> {meta.labelPlural} sur&nbsp;
            <strong>{includedCount}</strong> inclus dans le plan <strong>{planLabel}</strong>
            {activeAddonCount > 0 && (
              <>
                {" "}(dont {activeAddonCount} via add-on)
              </>
            )}.
            Deux options pour aller plus loin&nbsp;:
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2 pt-2">
          {/* Option 1 : add-on */}
          <div
            className={`rounded-lg border p-4 flex flex-col ${
              addonAvailable ? "" : "opacity-60"
            }`}
          >
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Plus className="h-4 w-4 text-primary" />
              Ajouter un add-on
            </div>
            <p className="text-xs text-muted-foreground mt-2 flex-1">
              {meta.addonUnit} pour <strong>{meta.addonPriceEur} €/mois</strong>.
              Facturation au prorata sur la période en cours, renouvelé automatiquement
              à chaque échéance. Retirable à tout moment.
            </p>
            {!addonAvailable && isCommercial && (
              <p className="text-[11px] text-destructive mt-2">
                Plafond d&apos;add-ons atteint sur ce plan.
              </p>
            )}
            {!isCommercial && (
              <p className="text-[11px] text-muted-foreground mt-2">
                Disponible uniquement avec un plan payant.
              </p>
            )}
            <Button
              variant="outline"
              size="sm"
              className="mt-3 w-full"
              disabled={!addonAvailable}
              onClick={() => goToBilling("addons")}
            >
              Acheter l&apos;add-on
            </Button>
          </div>

          {/* Option 2 : upgrade */}
          <div
            className={`rounded-lg border p-4 flex flex-col ${
              nextPlanMeta ? "border-primary/60 bg-primary/5" : "opacity-60"
            }`}
          >
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-primary" />
              Passer à l&apos;offre supérieure
            </div>
            {nextPlanMeta ? (
              <>
                <p className="text-xs text-muted-foreground mt-2 flex-1">
                  <strong>{nextPlanMeta.label}</strong> à{" "}
                  <strong>{nextPlanMeta.priceMonthly} €/mois</strong>. Inclut{" "}
                  {nextPlanMeta.features.slice(0, 3).join(" · ")}.
                  Prorata appliqué immédiatement.
                </p>
                <Button
                  size="sm"
                  className="mt-3 w-full"
                  onClick={() => goToBilling("plans")}
                >
                  Voir le plan {nextPlanMeta.label}
                  <ArrowUpRight className="h-3.5 w-3.5 ml-1" />
                </Button>
              </>
            ) : (
              <>
                <p className="text-xs text-muted-foreground mt-2 flex-1">
                  Vous êtes déjà sur l&apos;offre la plus complète. Pour des besoins
                  spécifiques, contactez <a className="underline" href="mailto:hello@aoriarh.fr">hello@aoriarh.fr</a>.
                </p>
                <Button size="sm" className="mt-3 w-full" disabled>
                  Offre maximale
                </Button>
              </>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Plus tard
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
