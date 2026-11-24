"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

type Mode = "off" | "shadow";
type Scope = "customers" | "paying" | "all";
type Validation = "confirmed" | "refuted" | "unanchored" | "unverified" | "all";

interface ReviewSettings {
  mode: Mode;
  scope: Scope;
  checks: { arithmetic: boolean; citations: boolean; llm: boolean };
  reviewer_model: string;
  monthly_budget_usd: number;
}

interface Overview {
  settings: ReviewSettings;
  force_off: boolean;
  reviewer_version: string;
  month_spend_usd: number;
  month_reviews: Record<string, number>;
  month_findings: Record<string, number>;
}

interface Finding {
  id: string;
  created_at: string;
  message_id: string;
  conversation_id: string;
  organisation_name: string | null;
  check: string;
  kind: string;
  validation: string;
  validation_reason: string | null;
  answer_excerpt: string;
  source_excerpt: string | null;
  source_label: string | null;
  explanation: string;
  proposed_fix: string | null;
}

const MODE_LABELS: Record<Mode, string> = {
  off: "Arrêt — aucun contrôle, aucun coût",
  shadow: "Observation — contrôle et enregistre, sans alerter personne",
};
const SCOPE_LABELS: Record<Scope, string> = {
  customers: "Toutes les réponses aux clients (hors équipe)",
  paying: "Clients payants uniquement",
  all: "Toutes les réponses, équipe comprise",
};
const CHECK_LABELS: Record<keyof ReviewSettings["checks"], string> = {
  arithmetic: "Montants (recalcul des opérations)",
  citations: "Articles du Code du travail cités introuvables",
  llm: "Relecteur IA avec contre-vérification (payant)",
};
const KIND_LABELS: Record<string, string> = {
  montant: "Montant",
  date: "Date / échéance",
  article: "Article mal cité",
  contradiction: "Contredit la source",
  conclusion: "Conclusion inversée",
  citation_introuvable: "Article introuvable",
};
const VALIDATION_LABELS: Record<string, string> = {
  confirmed: "Erreurs confirmées",
  refuted: "Réfutées par la contre-vérification",
  unanchored: "Citations inventées (écartées)",
  unverified: "Contre-vérification en échec",
  all: "Tous les constats",
};
const STATUS_LABELS: Record<string, string> = {
  clean: "sans erreur",
  flagged: "avec erreur",
  failed: "en échec",
  skipped: "non faits (budget)",
  running: "en cours",
};

export function AutoReviewPanel({
  onOpenAnswer,
}: {
  onOpenAnswer: (messageId: string) => void;
}) {
  const { data: session } = useSession();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [draft, setDraft] = useState<ReviewSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<Validation>("confirmed");
  const [findings, setFindings] = useState<Finding[] | null>(null);

  const load = useCallback(async () => {
    if (!session?.access_token) return;
    try {
      const data = await apiFetch<Overview>("/admin/quality/review/settings", {
        token: session.access_token,
      });
      setOverview(data);
      setDraft(data.settings);
    } catch {
      toast.error("Impossible de charger le réglage du contrôle qualité");
    }
  }, [session?.access_token]);

  const loadFindings = useCallback(async () => {
    if (!session?.access_token) return;
    try {
      const data = await apiFetch<Finding[]>(
        `/admin/quality/review/findings?validation=${validation}&limit=50`,
        { token: session.access_token }
      );
      setFindings(data);
    } catch {
      toast.error("Impossible de charger les constats");
    }
  }, [session?.access_token, validation]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadFindings();
  }, [loadFindings]);

  const save = async () => {
    if (!session?.access_token || !draft) return;
    setSaving(true);
    try {
      const data = await apiFetch<Overview>("/admin/quality/review/settings", {
        token: session.access_token,
        method: "PUT",
        body: JSON.stringify(draft),
      });
      setOverview(data);
      setDraft(data.settings);
      toast.success(
        data.settings.mode === "off"
          ? "Contrôle qualité arrêté"
          : "Contrôle qualité activé en observation"
      );
    } catch {
      toast.error("Le réglage n'a pas pu être enregistré");
    } finally {
      setSaving(false);
    }
  };

  if (!overview || !draft) {
    return <Skeleton className="h-64 w-full" />;
  }

  const changed = JSON.stringify(draft) !== JSON.stringify(overview.settings);
  const reviews = Object.values(overview.month_reviews).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            Contrôle qualité automatisé des réponses
            <Badge variant={overview.settings.mode === "off" ? "secondary" : "default"}>
              {overview.settings.mode === "off" ? "Arrêté" : "Observation"}
            </Badge>
          </CardTitle>
          <p className="text-muted-foreground text-sm">
            Chaque réponse est relue après son envoi, sans jamais la ralentir. Seules les
            erreurs sont recherchées, pas les imprécisions. En observation, rien n’est
            envoyé à personne : les constats servent à mesurer la fiabilité du contrôle.
          </p>
          {overview.force_off && (
            <p className="text-sm font-medium text-red-600">
              Coupure d’urgence active sur le serveur (QUALITY_REVIEW_FORCE_OFF) : le
              contrôle reste arrêté quel que soit ce réglage.
            </p>
          )}
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Mode</Label>
              <Select
                value={draft.mode}
                onValueChange={(v) => setDraft({ ...draft, mode: v as Mode })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(MODE_LABELS) as Mode[]).map((m) => (
                    <SelectItem key={m} value={m}>
                      {MODE_LABELS[m]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Réponses contrôlées</Label>
              <Select
                value={draft.scope}
                onValueChange={(v) => setDraft({ ...draft, scope: v as Scope })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(SCOPE_LABELS) as Scope[]).map((s) => (
                    <SelectItem key={s} value={s}>
                      {SCOPE_LABELS[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Contrôles</Label>
            {(Object.keys(CHECK_LABELS) as (keyof ReviewSettings["checks"])[]).map((key) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={draft.checks[key]}
                  onCheckedChange={(checked) =>
                    setDraft({ ...draft, checks: { ...draft.checks, [key]: checked === true } })
                  }
                />
                {CHECK_LABELS[key]}
              </label>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Modèle du relecteur</Label>
              <Select
                value={draft.reviewer_model}
                onValueChange={(v) => setDraft({ ...draft, reviewer_model: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["gpt-5.2", "gpt-5.6-terra", "gpt-5", "gpt-5-mini"].map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Budget mensuel (USD)</Label>
              <Input
                type="number"
                min={0}
                max={1000}
                value={draft.monthly_budget_usd}
                onChange={(e) =>
                  setDraft({ ...draft, monthly_budget_usd: Number(e.target.value) || 0 })
                }
              />
              <p className="text-muted-foreground text-xs">
                Une fois atteint, le relecteur IA s’arrête jusqu’au mois suivant.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            <p className="text-muted-foreground text-sm">
              Ce mois-ci : {reviews} réponse(s) contrôlée(s)
              {Object.entries(overview.month_reviews).length > 0 &&
                ` (${Object.entries(overview.month_reviews)
                  .map(([s, n]) => `${n} ${STATUS_LABELS[s] ?? s}`)
                  .join(", ")})`}{" "}
              · {overview.month_spend_usd.toFixed(2)} $ dépensés sur{" "}
              {overview.settings.monthly_budget_usd} $
            </p>
            <Button onClick={save} disabled={!changed || saving}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle className="text-base font-semibold">Constats</CardTitle>
          <Select value={validation} onValueChange={(v) => setValidation(v as Validation)}>
            <SelectTrigger className="w-72">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(VALIDATION_LABELS) as Validation[]).map((v) => (
                <SelectItem key={v} value={v}>
                  {VALIDATION_LABELS[v]}
                  {v !== "all" && overview.month_findings[v] !== undefined
                    ? ` (${overview.month_findings[v]} ce mois)`
                    : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent className="space-y-4">
          {findings === null ? (
            <Skeleton className="h-24 w-full" />
          ) : findings.length === 0 ? (
            <p className="text-muted-foreground text-sm">Aucun constat.</p>
          ) : (
            findings.map((f) => (
              <div key={f.id} className="space-y-2 rounded-md border p-4 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{KIND_LABELS[f.kind] ?? f.kind}</Badge>
                  <span className="text-muted-foreground">
                    {new Date(f.created_at).toLocaleString("fr-FR", {
                      timeZone: "Europe/Paris",
                    })}{" "}
                    · {f.organisation_name ?? "Organisation inconnue"}
                  </span>
                  <Button
                    variant="link"
                    size="sm"
                    className="ml-auto h-auto p-0"
                    onClick={() => onOpenAnswer(f.message_id)}
                  >
                    Voir la réponse
                  </Button>
                </div>
                <p>
                  <span className="font-medium">Dans la réponse : </span>
                  <span className="bg-red-50 dark:bg-red-950">{f.answer_excerpt}</span>
                </p>
                {f.source_excerpt && (
                  <p>
                    <span className="font-medium">
                      Source{f.source_label ? ` (${f.source_label})` : ""} :{" "}
                    </span>
                    <span className="bg-green-50 dark:bg-green-950">{f.source_excerpt}</span>
                  </p>
                )}
                <p>
                  <span className="font-medium">Pourquoi : </span>
                  {f.explanation}
                </p>
                {f.proposed_fix && (
                  <p>
                    <span className="font-medium">Correction proposée : </span>
                    {f.proposed_fix}
                  </p>
                )}
                {f.validation !== "confirmed" && f.validation_reason && (
                  <p className="text-muted-foreground">
                    <span className="font-medium">Écarté : </span>
                    {f.validation_reason}
                  </p>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
