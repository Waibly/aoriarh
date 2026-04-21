"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Clock, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchQuota, type QuotaInfo } from "@/lib/billing-api";

/**
 * Thin banner shown at the top of the dashboard for accounts on a trial
 * or nearing their monthly question quota.
 *
 * - Renders nothing for commercial plans (solo/equipe/groupe) under 80 % quota.
 * - Renders an orange banner with a day countdown during the 14-day trial.
 * - Renders a red banner when the monthly quota is >= 80 % (fair-use warning).
 */
export function TrialBanner() {
  const { data: session } = useSession();
  const [quota, setQuota] = useState<QuotaInfo | null>(null);

  useEffect(() => {
    const token = session?.access_token;
    if (!token) return;
    const load = () => {
      fetchQuota(token)
        .then(setQuota)
        .catch(() => {
          // Silent fail — banner simply doesn't render.
        });
    };
    load();
    window.addEventListener("quota-updated", load);
    return () => window.removeEventListener("quota-updated", load);
  }, [session?.access_token]);

  if (!quota) return null;

  // Trial countdown
  if (quota.plan === "gratuit" && quota.trial_ends_at) {
    const endsAt = new Date(quota.trial_ends_at);
    const now = new Date();
    const daysLeft = Math.ceil(
      (endsAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24),
    );

    if (daysLeft < 0) {
      return (
        <div className="flex items-center justify-between gap-4 border-b border-destructive/30 bg-destructive/10 px-6 py-3 text-sm">
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-4 w-4" />
            <span>Votre essai est terminé. Souscrivez pour continuer à utiliser AORIA RH.</span>
          </div>
          <Button asChild size="sm">
            <Link href="/billing">Choisir une offre</Link>
          </Button>
        </div>
      );
    }

    const dayLabel = daysLeft === 0 ? "se termine aujourd'hui" : daysLeft === 1 ? "se termine demain" : `se termine dans ${daysLeft} jours`;
    const color = daysLeft <= 3 ? "text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900" : "text-muted-foreground bg-muted/40 border-border";

    return (
      <div className={`flex items-center justify-between gap-4 border-b px-6 py-3 text-sm ${color}`}>
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4" />
          <span>Votre essai {dayLabel}.</span>
        </div>
        <Button asChild size="sm" variant={daysLeft <= 3 ? "default" : "outline"}>
          <Link href="/billing">Voir les offres</Link>
        </Button>
      </div>
    );
  }

  // Quota soft/hard warning on any plan
  if (quota.quota_status === "soft_warning" || quota.quota_status === "hard_warning") {
    const pct = quota.quota > 0 ? Math.round((quota.used / quota.quota) * 100) : 0;
    const severity = quota.quota_status === "hard_warning" ? "hard" : "soft";
    const classes =
      severity === "hard"
        ? "border-destructive/30 bg-destructive/10 text-destructive"
        : "border-orange-200 dark:border-orange-900 bg-orange-50 dark:bg-orange-950/30 text-orange-700 dark:text-orange-300";

    return (
      <div className={`flex items-center justify-between gap-4 border-b px-6 py-3 text-sm ${classes}`}>
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" />
          <span>
            {severity === "hard"
              ? `Vous avez dépassé votre quota mensuel (${pct} %).`
              : `Vous approchez de votre quota mensuel (${pct} %).`}
            {quota.booster_remaining > 0
              ? ` Pack booster actif (${quota.booster_remaining} questions restantes).`
              : ""}
          </span>
        </div>
        <Button asChild size="sm" variant={severity === "hard" ? "default" : "outline"}>
          <Link href="/billing">Gérer mon abonnement</Link>
        </Button>
      </div>
    );
  }

  return null;
}
