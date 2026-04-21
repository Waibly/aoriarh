import Link from "next/link";
import { ArrowRight, Check, Scale, Clock, Users } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-lg font-semibold">
            AORIA RH
          </Link>
          <nav className="flex items-center gap-2">
            <Button asChild variant="ghost" size="sm">
              <Link href="/pricing">Tarifs</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href="/login">Se connecter</Link>
            </Button>
            <Button asChild size="sm">
              <Link href="/register">Essai gratuit</Link>
            </Button>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <main className="flex-1">
        <section className="mx-auto max-w-5xl px-6 py-24 text-center">
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight">
            Votre assistant juridique RH,
            <br />
            fiable et toujours à jour
          </h1>
          <p className="mt-6 text-lg text-muted-foreground max-w-2xl mx-auto">
            Interrogez en langage naturel le Code du travail, votre convention collective
            et vos accords d&apos;entreprise. Obtenez des réponses sourcées, instantanées,
            pour gagner des heures sur chaque dossier RH.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row gap-3 justify-center">
            <Button asChild size="lg">
              <Link href="/register">
                Démarrer l&apos;essai gratuit (14 jours)
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/pricing">Voir les tarifs</Link>
            </Button>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Sans carte bancaire. Résiliable à tout moment.
          </p>
        </section>

        {/* Features */}
        <section className="border-t bg-muted/20">
          <div className="mx-auto max-w-5xl px-6 py-20 grid gap-10 md:grid-cols-3">
            <Feature
              icon={<Scale className="h-6 w-6" />}
              title="Sources juridiques officielles"
              description="Code du travail, conventions collectives KALI, Judilibre, Légifrance — mis à jour automatiquement."
            />
            <Feature
              icon={<Clock className="h-6 w-6" />}
              title="Des réponses en quelques secondes"
              description="Recherche sémantique sur vos documents internes et le corpus public, avec citations systématiques."
            />
            <Feature
              icon={<Users className="h-6 w-6" />}
              title="Pensé pour votre équipe RH"
              description="Multi-organisations, rôles dédiés, espace de travail cloisonné. Vos données restent chez vous."
            />
          </div>
        </section>

        {/* How it works */}
        <section>
          <div className="mx-auto max-w-5xl px-6 py-20">
            <h2 className="text-3xl font-bold text-center mb-12">Comment ça marche</h2>
            <div className="space-y-6 max-w-2xl mx-auto">
              <Step
                num="1"
                title="Créez votre espace en 30 secondes"
                text="Inscription sans carte bancaire, essai gratuit 14 jours immédiatement activé."
              />
              <Step
                num="2"
                title="Importez vos documents RH"
                text="Contrats, accords, notes internes — le système les indexe automatiquement et les sécurise."
              />
              <Step
                num="3"
                title="Posez vos questions"
                text="En français, comme à un juriste. Chaque réponse est argumentée et sourcée."
              />
            </div>
          </div>
        </section>

        {/* CTA final */}
        <section className="border-t bg-primary/5">
          <div className="mx-auto max-w-4xl px-6 py-20 text-center">
            <h2 className="text-3xl font-bold">Prêt à essayer ?</h2>
            <p className="mt-4 text-muted-foreground">
              14 jours gratuits. Pas de carte bancaire.
              À partir de 79 &euro; HT/mois ensuite.
            </p>
            <Button asChild size="lg" className="mt-8">
              <Link href="/register">
                Démarrer maintenant
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t">
        <div className="mx-auto max-w-6xl px-6 py-8 text-xs text-muted-foreground flex flex-col md:flex-row justify-between items-center gap-4">
          <p>&copy; {new Date().getFullYear()} AORIA RH. Tous droits réservés.</p>
          <nav className="flex gap-6">
            <Link href="/pricing" className="hover:text-foreground">Tarifs</Link>
            <a href="/docs/CGV.md" className="hover:text-foreground">CGV</a>
            <a href="/docs/POLITIQUE_CONFIDENTIALITE.md" className="hover:text-foreground">
              Confidentialité
            </a>
            <a href="mailto:hello@aoriarh.fr" className="hover:text-foreground">Contact</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

function Feature({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="text-center space-y-3">
      <div className="inline-flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {icon}
      </div>
      <h3 className="font-semibold text-lg">{title}</h3>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function Step({
  num,
  title,
  text,
}: {
  num: string;
  title: string;
  text: string;
}) {
  return (
    <div className="flex gap-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground font-semibold">
        {num}
      </div>
      <div>
        <h3 className="font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground mt-1">{text}</p>
      </div>
    </div>
  );
}
