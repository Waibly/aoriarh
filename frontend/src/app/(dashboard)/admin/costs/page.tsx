"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  DollarSign,
  MessageSquare,
  Upload,
  TrendingUp,
  Zap,
  Pencil,
  Check,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// --- Types ---

interface CostSummary {
  total_cost_usd: number;
  total_tokens_input: number;
  total_tokens_output: number;
  total_calls: number;
  avg_cost_per_question: number;
  avg_cost_per_ingestion: number;
  total_questions: number;
  total_ingestions: number;
}

interface CostByPeriod {
  period: string;
  cost_usd: number;
  tokens_input: number;
  tokens_output: number;
  calls: number;
}

interface CostByProvider {
  provider: string;
  model: string;
  operation_type: string;
  cost_usd: number;
  tokens_input: number;
  tokens_output: number;
  calls: number;
}

interface CostByOrganisation {
  organisation_id: string | null;
  organisation_name: string | null;
  cost_usd: number;
  cost_questions_usd: number;
  cost_ingestion_usd: number;
  total_questions: number;
  total_ingestions: number;
  calls: number;
}

interface CostByUser {
  user_id: string | null;
  user_email: string | null;
  cost_usd: number;
  cost_questions_usd: number;
  cost_ingestion_usd: number;
  total_questions: number;
  total_ingestions: number;
  calls: number;
}

interface PricingEntry {
  provider: string;
  model: string;
  price_input_per_million: number;
  price_output_per_million: number | null;
}

interface CostDashboard {
  summary: CostSummary;
  by_period: CostByPeriod[];
  by_provider: CostByProvider[];
  by_organisation: CostByOrganisation[];
  by_user: CostByUser[];
  pricing: PricingEntry[];
}

// --- Helpers ---

function formatUSD(value: number): string {
  if (value < 0.01 && value > 0) return `$${value.toFixed(6)}`;
  if (value < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toString();
}

function formatPeriod(period: string, granularity: string): string {
  const d = new Date(period);
  if (granularity === "day")
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
  if (granularity === "week")
    return `S${getWeekNumber(d)} ${d.toLocaleDateString("fr-FR", { month: "short" })}`;
  if (granularity === "month")
    return d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
  if (granularity === "year")
    return d.toLocaleDateString("fr-FR", { year: "numeric" });
  return period;
}

function getWeekNumber(d: Date): number {
  const target = new Date(d.valueOf());
  target.setDate(target.getDate() + 3 - ((target.getDay() + 6) % 7));
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  firstThursday.setDate(firstThursday.getDate() + 3 - ((firstThursday.getDay() + 6) % 7));
  return 1 + Math.round((target.getTime() - firstThursday.getTime()) / 604800000);
}

/** Fill missing periods so the chart X-axis is continuous */
function fillPeriods(
  data: CostByPeriod[],
  dateFrom: Date,
  dateTo: Date,
  granularity: string
): CostByPeriod[] {
  const existing = new Map(data.map((d) => [d.period.split("T")[0], d]));
  const filled: CostByPeriod[] = [];
  const cursor = new Date(dateFrom);

  // Align cursor to granularity start
  if (granularity === "week") {
    const dow = cursor.getDay();
    cursor.setDate(cursor.getDate() - ((dow + 6) % 7)); // Monday
  } else if (granularity === "month") {
    cursor.setDate(1);
  } else if (granularity === "year") {
    cursor.setMonth(0, 1);
  }

  while (cursor <= dateTo) {
    const key = cursor.toISOString().split("T")[0];
    const entry = existing.get(key);
    filled.push(
      entry || {
        period: cursor.toISOString(),
        cost_usd: 0,
        tokens_input: 0,
        tokens_output: 0,
        calls: 0,
      }
    );
    // Advance cursor
    if (granularity === "day") {
      cursor.setDate(cursor.getDate() + 1);
    } else if (granularity === "week") {
      cursor.setDate(cursor.getDate() + 7);
    } else if (granularity === "month") {
      cursor.setMonth(cursor.getMonth() + 1);
    } else if (granularity === "year") {
      cursor.setFullYear(cursor.getFullYear() + 1);
    }
  }
  return filled;
}

const OPERATION_LABELS: Record<string, string> = {
  condense: "Condensation",
  expand: "Expansion requête",
  generate: "Génération réponse",
  embedding: "Embedding",
  rerank: "Reranking",
};

const RANGE_OPTIONS = [
  { value: "7", label: "7 derniers jours" },
  { value: "30", label: "30 derniers jours" },
  { value: "90", label: "3 derniers mois" },
  { value: "365", label: "12 derniers mois" },
];

const GRANULARITY_OPTIONS = [
  { value: "day", label: "Jour" },
  { value: "week", label: "Semaine" },
  { value: "month", label: "Mois" },
  { value: "year", label: "Année" },
];

// --- Component ---

export default function AdminCostsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [dashboard, setDashboard] = useState<CostDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [range, setRange] = useState("30");
  const [granularity, setGranularity] = useState("day");

  // Pricing edit state
  const [editingPricing, setEditingPricing] = useState(false);
  const [pricingDraft, setPricingDraft] = useState<PricingEntry[]>([]);
  const [savingPricing, setSavingPricing] = useState(false);

  // LLM model switch state
  const [currentModel, setCurrentModel] = useState<string>("");
  const [availableModels, setAvailableModels] = useState<{ id: string; label: string; input_1m: number; output_1m: number }[]>([]);
  const [switchingModel, setSwitchingModel] = useState(false);

  const fetchLlmModel = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<{ current_model: string; available_models: { id: string; label: string; input_1m: number; output_1m: number }[] }>(
        "/admin/costs/llm-model", { token }
      );
      setCurrentModel(data.current_model);
      setAvailableModels(data.available_models);
    } catch { /* ignore */ }
  }, [token]);

  const handleSwitchModel = async (modelId: string) => {
    if (!token || modelId === currentModel) return;
    setSwitchingModel(true);
    try {
      await apiFetch("/admin/costs/llm-model", {
        method: "PUT",
        token,
        body: JSON.stringify({ model: modelId }),
      });
      setCurrentModel(modelId);
      toast.success(`Modèle changé : ${modelId}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSwitchingModel(false);
    }
  };

  const fetchDashboard = useCallback(async () => {
    if (!token) return;
    try {
      const today = new Date();
      const from = new Date(today);
      from.setDate(from.getDate() - parseInt(range));
      const dateFrom = from.toISOString().split("T")[0];
      const dateTo = today.toISOString().split("T")[0];

      const data = await apiFetch<CostDashboard>(
        `/admin/costs/dashboard?date_from=${dateFrom}&date_to=${dateTo}&granularity=${granularity}`,
        { token }
      );
      setDashboard(data);
    } catch {
      toast.error("Erreur lors du chargement des coûts");
    } finally {
      setLoading(false);
    }
  }, [token, range, granularity]);

  useEffect(() => {
    setLoading(true);
    fetchDashboard();
    fetchLlmModel();
  }, [fetchDashboard, fetchLlmModel]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Suivi des coûts API
        </h1>
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-20" />
              </CardContent>
            </Card>
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!dashboard) return null;

  const { summary, by_provider, by_organisation, by_user, pricing } =
    dashboard;

  // Fill periods for continuous X-axis
  const today = new Date();
  const dateFrom = new Date(today);
  dateFrom.setDate(dateFrom.getDate() - parseInt(range));
  const filledPeriods = fillPeriods(dashboard.by_period, dateFrom, today, granularity);

  // Find max cost in period for bar chart
  const maxPeriodCost = Math.max(...filledPeriods.map((p) => p.cost_usd), 0.001);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">
          Suivi des coûts API
        </h1>
        <div className="flex items-center gap-3">
          <Select value={range} onValueChange={setRange}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={granularity} onValueChange={setGranularity}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {GRANULARITY_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Coût total</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatUSD(summary.total_cost_usd)}
            </div>
            <p className="text-xs text-muted-foreground">
              {summary.total_calls.toLocaleString("fr-FR")} appels API
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Coût moyen / question
            </CardTitle>
            <MessageSquare className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatUSD(summary.avg_cost_per_question)}
            </div>
            <p className="text-xs text-muted-foreground">
              {summary.total_questions.toLocaleString("fr-FR")} questions
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Coût moyen / upload
            </CardTitle>
            <Upload className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatUSD(summary.avg_cost_per_ingestion)}
            </div>
            <p className="text-xs text-muted-foreground">
              {summary.total_ingestions.toLocaleString("fr-FR")} documents
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Tokens</CardTitle>
            <Zap className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {formatTokens(summary.total_tokens_input + summary.total_tokens_output)}
            </div>
            <p className="text-xs text-muted-foreground">
              {formatTokens(summary.total_tokens_input)} in /{" "}
              {formatTokens(summary.total_tokens_output)} out
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Timeline chart (CSS bars) with Y-axis */}
      {filledPeriods.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              Coûts par {granularity === "day" ? "jour" : granularity === "week" ? "semaine" : granularity === "month" ? "mois" : "année"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {(() => {
              const chartHeight = 180;
              const barArea = chartHeight - 20; // space for labels
              // Compute nice Y-axis ticks
              const yTicks = (() => {
                const steps = 4;
                const raw = maxPeriodCost / steps;
                const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
                const nice = Math.ceil(raw / magnitude) * magnitude;
                return Array.from({ length: steps + 1 }, (_, i) => nice * i);
              })();
              const yMax = yTicks[yTicks.length - 1] || maxPeriodCost;
              const labelStep = Math.max(1, Math.ceil(filledPeriods.length / 12));

              return (
                <div className="flex">
                  {/* Y-axis labels */}
                  <div
                    className="flex flex-col-reverse justify-between pr-2 text-right"
                    style={{ height: barArea }}
                  >
                    {yTicks.map((tick, i) => (
                      <span
                        key={i}
                        className="text-[10px] text-muted-foreground leading-none whitespace-nowrap"
                      >
                        {formatUSD(tick)}
                      </span>
                    ))}
                  </div>
                  {/* Chart area */}
                  <div className="flex-1 min-w-0">
                    {/* Grid lines + bars */}
                    <div
                      className="relative border-l border-b border-border"
                      style={{ height: barArea }}
                    >
                      {/* Horizontal grid lines */}
                      {yTicks.slice(1).map((tick, i) => (
                        <div
                          key={i}
                          className="absolute left-0 right-0 border-t border-border/40"
                          style={{
                            bottom: `${(tick / yMax) * 100}%`,
                          }}
                        />
                      ))}
                      {/* Bars */}
                      <div className="absolute inset-0 flex items-end gap-[2px] px-[2px]">
                        {filledPeriods.map((p, i) => {
                          const pct = yMax > 0 ? (p.cost_usd / yMax) * 100 : 0;
                          return (
                            <div
                              key={i}
                              className="group relative flex-1 min-w-0"
                              style={{ height: "100%" }}
                            >
                              <div
                                className="absolute bottom-0 left-0 right-0 rounded-t bg-primary/70 transition-colors hover:bg-primary"
                                style={{
                                  height: `${Math.max(pct, 0.5)}%`,
                                }}
                              />
                              {/* Tooltip */}
                              <div className="pointer-events-none absolute -top-14 left-1/2 z-10 hidden -translate-x-1/2 rounded-md bg-popover border border-border px-2.5 py-1.5 text-xs text-popover-foreground shadow-md group-hover:block whitespace-nowrap">
                                <div className="font-medium">
                                  {formatPeriod(p.period, granularity)}
                                </div>
                                <div>
                                  {formatUSD(p.cost_usd)} &middot;{" "}
                                  {p.calls} appels
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    {/* X-axis labels */}
                    <div className="flex gap-[2px] px-[2px] mt-1">
                      {filledPeriods.map((p, i) => (
                        <div
                          key={i}
                          className="flex-1 min-w-0 text-center text-[10px] text-muted-foreground truncate"
                        >
                          {i % labelStep === 0 || i === filledPeriods.length - 1
                            ? formatPeriod(p.period, granularity)
                            : ""}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })()}
          </CardContent>
        </Card>
      )}

      {/* Tabs: Provider / Organisation / User / Pricing */}
      {/* LLM Model Switch */}
      {availableModels.length > 0 && (
        <Card>
          <CardContent className="flex items-center gap-3 py-3">
            <span className="text-sm font-medium">Modèle LLM :</span>
            <div className="flex gap-1.5">
              {availableModels.map((m) => (
                <Button
                  key={m.id}
                  variant={m.id === currentModel ? "default" : "outline"}
                  size="sm"
                  disabled={switchingModel}
                  onClick={() => handleSwitchModel(m.id)}
                  className="text-xs"
                >
                  {m.label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="organisation">
        <TabsList>
          <TabsTrigger value="organisation">Par organisation</TabsTrigger>
          <TabsTrigger value="user">Par utilisateur</TabsTrigger>
          <TabsTrigger value="provider">Par modèle</TabsTrigger>
          <TabsTrigger value="pricing">Tarifs configurés</TabsTrigger>
        </TabsList>

        {/* By Provider/Model */}
        <TabsContent value="provider">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Provider</TableHead>
                    <TableHead>Modèle</TableHead>
                    <TableHead>Opération</TableHead>
                    <TableHead className="text-right">Appels</TableHead>
                    <TableHead className="text-right">Tokens in</TableHead>
                    <TableHead className="text-right">Tokens out</TableHead>
                    <TableHead className="text-right">Coût</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {by_provider.map((row, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <Badge variant="outline">{row.provider}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {row.model}
                      </TableCell>
                      <TableCell>
                        {OPERATION_LABELS[row.operation_type] ||
                          row.operation_type}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.calls.toLocaleString("fr-FR")}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatTokens(row.tokens_input)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatTokens(row.tokens_output)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatUSD(row.cost_usd)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {by_provider.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={7}
                        className="text-center text-muted-foreground py-8"
                      >
                        Aucune donnée sur cette période
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* By Organisation */}
        <TabsContent value="organisation">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Organisation</TableHead>
                    <TableHead className="text-right">Questions</TableHead>
                    <TableHead className="text-right">Coût questions</TableHead>
                    <TableHead className="text-right">Ingestions</TableHead>
                    <TableHead className="text-right">Coût ingestion</TableHead>
                    <TableHead className="text-right">Coût total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {by_organisation.map((row, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">
                        {row.organisation_name || (
                          <span className="text-muted-foreground italic">
                            Non attribué
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.total_questions.toLocaleString("fr-FR")}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatUSD(row.cost_questions_usd)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.total_ingestions.toLocaleString("fr-FR")}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatUSD(row.cost_ingestion_usd)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatUSD(row.cost_usd)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {by_organisation.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center text-muted-foreground py-8"
                      >
                        Aucune donnée sur cette période
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* By User */}
        <TabsContent value="user">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Utilisateur</TableHead>
                    <TableHead className="text-right">Questions</TableHead>
                    <TableHead className="text-right">Coût questions</TableHead>
                    <TableHead className="text-right">Ingestions</TableHead>
                    <TableHead className="text-right">Coût ingestion</TableHead>
                    <TableHead className="text-right">Coût total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {by_user.map((row, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-medium">
                        {row.user_email || (
                          <span className="text-muted-foreground italic">
                            Non attribué
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.total_questions.toLocaleString("fr-FR")}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatUSD(row.cost_questions_usd)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.total_ingestions.toLocaleString("fr-FR")}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatUSD(row.cost_ingestion_usd)}
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {formatUSD(row.cost_usd)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {by_user.length === 0 && (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center text-muted-foreground py-8"
                      >
                        Aucune donnée sur cette période
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Pricing (editable) */}
        <TabsContent value="pricing">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">
                Tarifs actuels (USD / 1M tokens)
              </CardTitle>
              {!editingPricing ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setPricingDraft(
                      pricing.map((p) => ({ ...p }))
                    );
                    setEditingPricing(true);
                  }}
                >
                  <Pencil className="mr-2 h-3.5 w-3.5" />
                  Modifier
                </Button>
              ) : (
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditingPricing(false)}
                    disabled={savingPricing}
                  >
                    <X className="mr-1 h-3.5 w-3.5" />
                    Annuler
                  </Button>
                  <Button
                    size="sm"
                    disabled={savingPricing}
                    onClick={async () => {
                      if (!token) return;
                      setSavingPricing(true);
                      try {
                        const updated = await apiFetch<PricingEntry[]>(
                          "/admin/costs/pricing",
                          {
                            token,
                            method: "PUT",
                            body: JSON.stringify(pricingDraft),
                          }
                        );
                        setDashboard((prev) =>
                          prev ? { ...prev, pricing: updated } : prev
                        );
                        setEditingPricing(false);
                        toast.success("Tarifs mis à jour");
                      } catch {
                        toast.error("Erreur lors de la mise à jour");
                      } finally {
                        setSavingPricing(false);
                      }
                    }}
                  >
                    <Check className="mr-1 h-3.5 w-3.5" />
                    Enregistrer
                  </Button>
                </div>
              )}
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Provider</TableHead>
                    <TableHead>Modèle</TableHead>
                    <TableHead className="text-right">Input ($/1M)</TableHead>
                    <TableHead className="text-right">Output ($/1M)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(editingPricing ? pricingDraft : pricing).map(
                    (row, i) => (
                      <TableRow key={i}>
                        <TableCell>
                          <Badge variant="outline">{row.provider}</Badge>
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {row.model}
                        </TableCell>
                        <TableCell className="text-right">
                          {editingPricing ? (
                            <Input
                              type="number"
                              step="0.0001"
                              min="0"
                              className="w-28 ml-auto text-right h-8"
                              value={row.price_input_per_million}
                              onChange={(e) => {
                                const val = parseFloat(e.target.value) || 0;
                                setPricingDraft((prev) =>
                                  prev.map((p, j) =>
                                    j === i
                                      ? { ...p, price_input_per_million: val }
                                      : p
                                  )
                                );
                              }}
                            />
                          ) : (
                            `$${row.price_input_per_million.toFixed(4)}`
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {editingPricing ? (
                            row.price_output_per_million !== null ? (
                              <Input
                                type="number"
                                step="0.0001"
                                min="0"
                                className="w-28 ml-auto text-right h-8"
                                value={row.price_output_per_million}
                                onChange={(e) => {
                                  const val =
                                    parseFloat(e.target.value) || 0;
                                  setPricingDraft((prev) =>
                                    prev.map((p, j) =>
                                      j === i
                                        ? {
                                            ...p,
                                            price_output_per_million: val,
                                          }
                                        : p
                                    )
                                  );
                                }}
                              />
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )
                          ) : row.price_output_per_million !== null ? (
                            `$${row.price_output_per_million.toFixed(4)}`
                          ) : (
                            "—"
                          )}
                        </TableCell>
                      </TableRow>
                    )
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
