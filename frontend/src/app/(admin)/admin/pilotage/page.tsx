"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import {
  TrendingUp,
  Wallet,
  Percent,
  Users,
  AlertTriangle,
  ThumbsUp,
  MessageSquare,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
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
import { InfoTooltip } from "@/components/admin/info-tooltip";
import { cn } from "@/lib/utils";

type AtRiskAccount = {
  account_id: string;
  account_name: string | null;
  owner_email: string | null;
  plan: string;
  reason: "trial_expiring" | "past_due" | "inactive";
  detail: string | null;
};

type Overview = {
  mrr_eur: number;
  arr_eur: number;
  subscriptions_by_plan: Record<string, number>;
  infra_cost_eur_30d: number;
  gross_margin_eur: number;
  infra_pct_of_mrr: number | null;
  arpu_eur: number | null;
  active_subscriptions: number;
  new_customers_30d: number;
  trial_active: number;
  trial_to_paid_rate_30d: number | null;
  promo_activations_30d: number;
  monthly_churn_pct: number;
  accounts_past_due: number;
  at_risk: AtRiskAccount[];
  questions_30d: number;
  questions_trend_pct: number | null;
  satisfaction_rate: number | null;
  feedback_negative_rate: number;
  no_sources_rate: number;
};

const REASON_LABELS: Record<AtRiskAccount["reason"], string> = {
  trial_expiring: "Essai bientôt expiré",
  past_due: "Paiement en retard",
  inactive: "Client dormant",
};

const REASON_VARIANTS: Record<
  AtRiskAccount["reason"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  trial_expiring: "secondary",
  past_due: "destructive",
  inactive: "outline",
};

const fmtEur = (n: number) =>
  new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(n);

const fmtEur2 = (n: number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(
    n
  );

const fmtPct = (n: number | null, digits = 0) =>
  n === null ? "—" : `${(n * 100).toFixed(digits)} %`;

function KpiCard({
  title,
  value,
  sub,
  icon: Icon,
  tone = "neutral",
  info,
}: {
  title: string;
  value: string;
  sub?: React.ReactNode;
  icon: React.ElementType;
  tone?: "neutral" | "good" | "warn" | "bad";
  info?: React.ReactNode;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-600 dark:text-emerald-400"
      : tone === "warn"
        ? "text-orange-600 dark:text-orange-400"
        : tone === "bad"
          ? "text-destructive"
          : "text-foreground";
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-muted-foreground flex items-center gap-1.5 text-sm font-medium">
          {title}
          {info && <InfoTooltip>{info}</InfoTooltip>}
        </CardTitle>
        <Icon className="text-muted-foreground h-4 w-4" />
      </CardHeader>
      <CardContent>
        <div className={cn("text-2xl font-bold tabular-nums", toneClass)}>
          {value}
        </div>
        {sub && <p className="text-muted-foreground mt-1 text-xs">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-muted-foreground mt-2 text-xs font-semibold tracking-wide uppercase">
      {children}
    </h2>
  );
}

export default function AdminPilotagePage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const d = await apiFetch<Overview>("/admin/business/overview", { token });
      setData(d);
    } catch (err) {
      setError(true);
      toast.error(err instanceof Error ? err.message : "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
        <p className="text-muted-foreground">
          Impossible de charger le tableau de bord.
        </p>
        <button onClick={load} className="text-primary text-sm underline">
          Réessayer
        </button>
      </div>
    );
  }

  if (!data) return null;

  const marginTone = data.gross_margin_eur >= 0 ? "good" : "bad";
  const infraTone =
    data.infra_pct_of_mrr === null
      ? "neutral"
      : data.infra_pct_of_mrr > 30
        ? "warn"
        : "good";
  const churnTone =
    data.monthly_churn_pct > 5
      ? "bad"
      : data.monthly_churn_pct > 2
        ? "warn"
        : "good";
  const satisfactionTone =
    data.satisfaction_rate === null
      ? "neutral"
      : data.satisfaction_rate >= 0.8
        ? "good"
        : data.satisfaction_rate >= 0.6
          ? "warn"
          : "bad";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tableau de bord</h1>
        <p className="text-muted-foreground text-sm">
          Vue business : revenu, rentabilité, croissance et risques. Montants en
          euros.
        </p>
      </div>

      {/* Revenu & rentabilité */}
      <SectionTitle>Revenu &amp; rentabilité</SectionTitle>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="MRR"
          value={fmtEur(data.mrr_eur)}
          sub={`ARR estimé ${fmtEur(data.arr_eur)}`}
          icon={TrendingUp}
          info={
            <>
              <b>Revenu mensuel récurrent</b> (Monthly Recurring Revenue) :
              somme des abonnements payants actifs, ramenée au mois (un
              abonnement annuel compte pour 1/12). L&apos;ARR est simplement le
              MRR × 12.
            </>
          }
        />
        <KpiCard
          title="Marge brute (30 j)"
          value={fmtEur(data.gross_margin_eur)}
          sub="MRR − coût d'infrastructure"
          icon={Wallet}
          tone={marginTone}
          info={
            <>
              <b>MRR − coût d&apos;infrastructure des 30 derniers jours.</b> Ce
              qu&apos;il reste après les coûts techniques variables (IA,
              embeddings). Ne déduit pas les charges fixes (salaires,
              hébergement…).
            </>
          }
        />
        <KpiCard
          title="Coût infra (30 j)"
          value={fmtEur(data.infra_cost_eur_30d)}
          sub={
            data.infra_pct_of_mrr === null
              ? "Pas de MRR"
              : `${data.infra_pct_of_mrr} % du MRR`
          }
          icon={Percent}
          tone={infraTone}
          info={
            <>
              Coût des appels aux fournisseurs IA (OpenAI, Voyage) sur 30 jours,
              facturés en dollars et convertis en euros au taux configuré. Le
              pourcentage indique la part du MRR absorbée par l&apos;infra (sain
              en dessous de ~30 %).
            </>
          }
        />
        <KpiCard
          title="ARPU"
          value={data.arpu_eur === null ? "—" : fmtEur2(data.arpu_eur)}
          sub={`${data.active_subscriptions} abonnement${data.active_subscriptions > 1 ? "s" : ""} actif${data.active_subscriptions > 1 ? "s" : ""}`}
          icon={Users}
          info={
            <>
              <b>Revenu moyen par compte</b> (Average Revenue Per User) : MRR
              divisé par le nombre d&apos;abonnements payants actifs.
            </>
          }
        />
      </div>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">
            Abonnements par plan
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          {Object.entries(data.subscriptions_by_plan).map(([plan, count]) => (
            <div key={plan} className="flex items-center gap-2">
              <Badge variant="outline">{getPlanLabel(plan)}</Badge>
              <span className="text-sm tabular-nums">{count}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Croissance */}
      <SectionTitle>Croissance &amp; acquisition</SectionTitle>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Nouveaux clients (30 j)"
          value={String(data.new_customers_30d)}
          icon={TrendingUp}
          info="Nombre d'abonnements payants souscrits durant les 30 derniers jours."
        />
        <KpiCard
          title="Essais actifs"
          value={String(data.trial_active)}
          icon={Users}
          info="Comptes actuellement en période d'essai gratuite (plan gratuit, statut « trialing ») — autant de conversions potentielles."
        />
        <KpiCard
          title="Conversion essai → payant"
          value={fmtPct(data.trial_to_paid_rate_30d)}
          sub="Sur 30 j (estimation)"
          icon={Percent}
          info={
            <>
              Estimation : nouveaux clients payants (30 j) rapportés au total «
              nouveaux payants + essais en cours ». Indique grossièrement
              l&apos;efficacité du tunnel d&apos;essai. À affiner par cohorte
              plus tard.
            </>
          }
        />
        <KpiCard
          title="Activations liens promo (30 j)"
          value={String(data.promo_activations_30d)}
          icon={TrendingUp}
          info="Nombre de comptes ayant activé un lien d'invitation promo (plan Invité) durant les 30 derniers jours."
        />
      </div>

      {/* Risque */}
      <SectionTitle>Risque</SectionTitle>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Churn mensuel"
          value={`${data.monthly_churn_pct} %`}
          icon={AlertTriangle}
          tone={churnTone}
          info={
            <>
              <b>Taux d&apos;attrition.</b> Résiliations sur les 30 derniers
              jours rapportées au nombre d&apos;abonnements actifs. Vert &lt; 2
              %, orange 2–5 %, rouge &gt; 5 %.
            </>
          }
        />
        <KpiCard
          title="Paiements en retard"
          value={String(data.accounts_past_due)}
          icon={AlertTriangle}
          tone={data.accounts_past_due > 0 ? "bad" : "good"}
          info="Abonnements au statut « past_due » : un prélèvement Stripe a échoué. Revenu à risque immédiat — à relancer."
        />
      </div>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
            Comptes à surveiller{" "}
            <span className="text-muted-foreground font-normal">
              ({data.at_risk.length})
            </span>
            <InfoTooltip>
              Comptes nécessitant une action : essai expirant dans moins de 14
              jours, paiement en retard, ou client payant sans aucune question
              posée sur les 30 derniers jours (dormant).
            </InfoTooltip>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.at_risk.length === 0 ? (
            <p className="text-muted-foreground py-4 text-sm">
              Aucun compte à risque détecté.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Client</TableHead>
                  <TableHead>Propriétaire</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Motif</TableHead>
                  <TableHead>Détail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.at_risk.map((a) => (
                  <TableRow key={`${a.reason}-${a.account_id}`}>
                    <TableCell className="font-medium">
                      {a.account_name ?? "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {a.owner_email ?? "—"}
                    </TableCell>
                    <TableCell>{getPlanLabel(a.plan)}</TableCell>
                    <TableCell>
                      <Badge variant={REASON_VARIANTS[a.reason]}>
                        {REASON_LABELS[a.reason]}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {a.detail ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Valeur produit */}
      <SectionTitle>Valeur produit</SectionTitle>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Satisfaction"
          value={fmtPct(data.satisfaction_rate)}
          sub="Avis positifs / avis exprimés"
          icon={ThumbsUp}
          tone={satisfactionTone}
          info={
            <>
              Part d&apos;avis positifs (👍) parmi les réponses notées par les
              utilisateurs sur 30 jours. Les réponses non notées sont exclues du
              calcul. Vert ≥ 80 %, orange 60–80 %, rouge &lt; 60 %.
            </>
          }
        />
        <KpiCard
          title="Questions (30 j)"
          value={new Intl.NumberFormat("fr-FR").format(data.questions_30d)}
          sub={
            data.questions_trend_pct === null
              ? "Pas de comparaison"
              : `${data.questions_trend_pct > 0 ? "+" : ""}${data.questions_trend_pct} % vs 30 j préc.`
          }
          icon={MessageSquare}
          info="Nombre de questions posées sur 30 jours (signal d'usage), avec l'évolution par rapport aux 30 jours précédents."
        />
        <KpiCard
          title="Avis négatifs"
          value={fmtPct(data.feedback_negative_rate, 1)}
          icon={AlertTriangle}
          tone={
            data.feedback_negative_rate > 0.15
              ? "bad"
              : data.feedback_negative_rate > 0.05
                ? "warn"
                : "good"
          }
          info="Part de réponses notées 👎 parmi toutes les réponses des 30 derniers jours. Vert < 5 %, orange 5–15 %, rouge > 15 %."
        />
        <KpiCard
          title="Questions sans réponse"
          value={fmtPct(data.no_sources_rate, 1)}
          sub={
            <Link href="/admin/quality" className="text-primary underline">
              Voir la qualité
            </Link>
          }
          icon={AlertTriangle}
          tone={data.no_sources_rate > 0.05 ? "warn" : "good"}
          info="Part de questions dans le périmètre pour lesquelles le RAG n'a trouvé aucune source (hors refus « hors sujet »). Signale un manque dans le corpus = promesse non tenue."
        />
      </div>
    </div>
  );
}
