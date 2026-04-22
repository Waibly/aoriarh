"use client";

import { useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PLANS, COMMERCIAL_PLANS, type BillingCycle, type PlanCode } from "@/lib/plans";

/**
 * Public pricing page.
 *
 * - Unauthenticated visitors are redirected to /register?plan=...&cycle=...
 *   so they complete signup first, then land on /billing where their
 *   selection is honored.
 * - Authenticated users go straight to /billing with their choice.
 */
export default function PricingPage() {
  const { status } = useSession();
  const [cycle, setCycle] = useState<BillingCycle>("monthly");

  const isAuthed = status === "authenticated";

  const hrefForPlan = (plan: PlanCode): string => {
    const params = new URLSearchParams({ plan, cycle });
    return isAuthed ? `/billing?${params.toString()}` : `/register?${params.toString()}`;
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-lg font-semibold">
            AORIA RH
          </Link>
          <nav className="flex items-center gap-3">
            {isAuthed ? (
              <Button asChild variant="outline" size="sm">
                <Link href="/chat">Accéder à l&apos;application</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/login">Se connecter</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href="/register">Essai gratuit 14 jours</Link>
                </Button>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="text-center space-y-3 mb-12">
          <h1 className="text-4xl font-bold tracking-tight">Nos offres</h1>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Tous nos plans incluent un essai gratuit de 14 jours sans carte bancaire.
            Résiliable à tout moment.
          </p>
          <div className="inline-flex items-center gap-1 rounded-lg border p-1 bg-muted/30 mt-6">
            <button
              onClick={() => setCycle("monthly")}
              className={`px-4 py-1.5 text-sm rounded-md transition ${
                cycle === "monthly" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Mensuel
            </button>
            <button
              onClick={() => setCycle("yearly")}
              className={`px-4 py-1.5 text-sm rounded-md transition ${
                cycle === "yearly" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Annuel <span className="text-primary text-xs ml-1">(2 mois offerts)</span>
            </button>
          </div>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {COMMERCIAL_PLANS.map((code) => {
            const plan = PLANS[code];
            const price = cycle === "monthly" ? plan.priceMonthly : plan.priceYearly;
            const featured = plan.featured === true;
            return (
              <Card
                key={code}
                className={`relative ${featured ? "border-primary shadow-lg md:scale-105" : ""}`}
              >
                {featured && (
                  <Badge className="absolute -top-2 left-1/2 -translate-x-1/2">
                    Le plus choisi
                  </Badge>
                )}
                <CardHeader>
                  <CardTitle className="text-xl">{plan.label}</CardTitle>
                  <CardDescription className="min-h-[40px]">
                    {plan.target}
                  </CardDescription>
                  <div className="flex items-baseline gap-1 pt-4">
                    <span className="text-4xl font-bold">{price} €</span>
                    <span className="text-sm text-muted-foreground">
                      HT /{cycle === "monthly" ? "mois" : "an"}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  <ul className="space-y-2.5 text-sm">
                    {plan.features.map((f) => (
                      <li key={f} className="flex gap-2">
                        <Check className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>
                  <Button
                    className="w-full"
                    variant={featured ? "default" : "outline"}
                    asChild
                  >
                    <Link href={hrefForPlan(code)}>
                      {isAuthed ? "Souscrire" : "Démarrer l'essai gratuit"}
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>

        <div className="mt-12 max-w-3xl mx-auto space-y-4">
          <h2 className="text-lg font-semibold text-center">Quelques précisions</h2>

          <div className="rounded-lg border bg-muted/30 p-5 text-sm space-y-1.5">
            <p className="font-semibold">Chat in-app</p>
            <p className="text-muted-foreground">
              Un chat intégré directement dans l&apos;application pour poser vos questions
              juridiques RH, consulter les sources citées et retrouver l&apos;historique
              de vos échanges — pas besoin d&apos;outil tiers ni d&apos;email.
            </p>
          </div>

          <div className="rounded-lg border bg-muted/30 p-5 text-sm space-y-1.5">
            <p className="font-semibold">Add-ons</p>
            <p className="text-muted-foreground">
              Options payantes à activer à la carte sur votre abonnement sans changer
              d&apos;offre : utilisateur supplémentaire (15 €/mois, jusqu&apos;à 3 en plus),
              organisation supplémentaire (19 €/mois), pack +500 documents par organisation
              (10 €/mois). Retirables à tout moment.
            </p>
          </div>

          <div className="rounded-lg border bg-muted/30 p-5 text-sm space-y-1.5">
            <p className="font-semibold">Fair use</p>
            <p className="text-muted-foreground">
              Les quotas de questions sont mensuels et partagés entre tous les utilisateurs
              de votre équipe. Aucun blocage sec : en cas de dépassement, vous pouvez simplement
              passer à l&apos;offre supérieure ou acheter un pack booster ponctuel
              (+500 questions, 25 €). Les questions des boosters ne périment pas tant que votre
              compte est actif.
            </p>
          </div>
        </div>

        <div className="mt-6 text-center text-xs text-muted-foreground">
          <Link href="/cgv" className="underline hover:text-foreground">
            Conditions générales de vente
          </Link>
          {" · "}
          <Link href="/politique-confidentialite" className="underline hover:text-foreground">
            Politique de confidentialité
          </Link>
        </div>
      </main>
    </div>
  );
}
