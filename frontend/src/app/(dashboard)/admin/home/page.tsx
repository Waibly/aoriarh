"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Users,
  FileText,
  MessageSquare,
  DollarSign,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Database,
  Cpu,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface DashboardStats {
  total_users: number;
  active_users: number;
  total_organisations: number;
  total_documents: number;
  indexed_documents: number;
  pending_documents: number;
  error_documents: number;
  bocc_reserve: number;
  total_chunks: number;
  questions_7d: number;
  questions_today: number;
  ingestions_7d: number;
  cost_7d: number;
  questions_30d: number;
  cost_30d: number;
  last_sync_type: string | null;
  last_sync_status: string | null;
  last_sync_at: string | null;
  failed_syncs_24h: number;
  current_model: string;
}

function formatCost(v: number): string {
  if (v < 0.01 && v > 0) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export default function AdminHomePage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchStats = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<DashboardStats>("/admin/dashboard/", { token });
      setStats(data);
    } catch {
      toast.error("Erreur lors du chargement du tableau de bord");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [fetchStats]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Tableau de bord</h1>
        <div className="grid gap-4 md:grid-cols-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-40" />)}
        </div>
      </div>
    );
  }

  if (!stats) return null;

  const hasAlerts = stats.error_documents > 0 || stats.failed_syncs_24h > 0 || stats.pending_documents > 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Tableau de bord</h1>

      {/* Alerts banner */}
      {hasAlerts && (
        <Card className="border-orange-300 bg-orange-50 dark:border-orange-800 dark:bg-orange-950/30">
          <CardContent className="flex items-center gap-3 py-3">
            <AlertTriangle className="h-5 w-5 text-orange-600 shrink-0" />
            <div className="flex flex-wrap gap-3 text-sm">
              {stats.error_documents > 0 && (
                <span className="text-orange-800 dark:text-orange-300">
                  <strong>{stats.error_documents}</strong> document{stats.error_documents > 1 ? "s" : ""} en erreur
                </span>
              )}
              {stats.failed_syncs_24h > 0 && (
                <span className="text-orange-800 dark:text-orange-300">
                  <strong>{stats.failed_syncs_24h}</strong> sync{stats.failed_syncs_24h > 1 ? "s" : ""} échouée{stats.failed_syncs_24h > 1 ? "s" : ""} (24h)
                </span>
              )}
              {stats.pending_documents > 0 && (
                <span className="text-orange-800 dark:text-orange-300">
                  <strong>{stats.pending_documents}</strong> document{stats.pending_documents > 1 ? "s" : ""} en attente d&apos;indexation
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Row 1: Key metrics */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Questions aujourd&apos;hui</CardTitle>
            <MessageSquare className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.questions_today}</div>
            <p className="text-xs text-muted-foreground">
              {stats.questions_7d} cette semaine · {stats.questions_30d} ce mois
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Coûts API (7j)</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{formatCost(stats.cost_7d)}</div>
            <p className="text-xs text-muted-foreground">
              {formatCost(stats.cost_30d)} sur 30 jours
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Utilisateurs</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.active_users}</div>
            <p className="text-xs text-muted-foreground">
              {stats.total_users} total · {stats.total_organisations} organisation{stats.total_organisations > 1 ? "s" : ""}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Modèle LLM</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.current_model}</div>
            <p className="text-xs text-muted-foreground">
              {stats.questions_7d > 0 ? `~${formatCost(stats.cost_7d / stats.questions_7d)}/question` : "—"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Row 2: Documents + Syncs + Index */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Documents health */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-4 w-4" />
              Base documentaire
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Documents total</span>
              <span className="font-medium">{stats.total_documents.toLocaleString("fr-FR")}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Indexés</span>
              <span className="flex items-center gap-1.5 font-medium text-green-600">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {stats.indexed_documents.toLocaleString("fr-FR")}
              </span>
            </div>
            {stats.pending_documents > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">En attente</span>
                <span className="flex items-center gap-1.5 font-medium text-orange-600">
                  <Clock className="h-3.5 w-3.5" />
                  {stats.pending_documents.toLocaleString("fr-FR")}
                </span>
              </div>
            )}
            {stats.error_documents > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">En erreur</span>
                <span className="flex items-center gap-1.5 font-medium text-red-600">
                  <XCircle className="h-3.5 w-3.5" />
                  {stats.error_documents}
                </span>
              </div>
            )}
            {stats.bocc_reserve > 0 && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">BOCC en réserve</span>
                <span className="text-sm font-medium text-muted-foreground">
                  {stats.bocc_reserve.toLocaleString("fr-FR")}
                </span>
              </div>
            )}
            <div className="border-t pt-2 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Chunks Qdrant</span>
              <span className="flex items-center gap-1.5 font-medium">
                <Database className="h-3.5 w-3.5 text-muted-foreground" />
                {stats.total_chunks.toLocaleString("fr-FR")}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Sync status */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <RefreshCw className="h-4 w-4" />
              Synchronisations
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {stats.last_sync_at ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Dernière sync</span>
                  <span className="text-sm font-medium">
                    {new Date(stats.last_sync_at).toLocaleDateString("fr-FR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Type</span>
                  <Badge variant="outline" className="rounded-full text-xs">
                    {stats.last_sync_type === "jurisprudence" ? "Jurisprudence" :
                     stats.last_sync_type === "code_travail" ? "Code travail" : "CCN"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Statut</span>
                  {stats.last_sync_status === "success" ? (
                    <Badge variant="outline" className="rounded-full border-green-500 bg-green-500/10 text-green-600 text-xs">
                      <CheckCircle2 className="mr-1 h-3 w-3" /> Succès
                    </Badge>
                  ) : stats.last_sync_status === "error" ? (
                    <Badge variant="outline" className="rounded-full border-red-500 bg-red-500/10 text-red-600 text-xs">
                      <XCircle className="mr-1 h-3 w-3" /> Erreur
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="rounded-full text-xs">
                      {stats.last_sync_status}
                    </Badge>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Aucune synchronisation</p>
            )}
            {stats.failed_syncs_24h > 0 && (
              <div className="border-t pt-2 flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Échecs (24h)</span>
                <span className="font-medium text-red-600">{stats.failed_syncs_24h}</span>
              </div>
            )}
            <div className="border-t pt-2 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Ingestions (7j)</span>
              <span className="font-medium">{stats.ingestions_7d}</span>
            </div>
          </CardContent>
        </Card>

        {/* Usage trends */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              Activité
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Questions (7j)</span>
              <span className="font-medium">{stats.questions_7d}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Questions (30j)</span>
              <span className="font-medium">{stats.questions_30d}</span>
            </div>
            <div className="border-t pt-2 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Coût moyen/question</span>
              <span className="font-medium">
                {stats.questions_30d > 0 ? formatCost(stats.cost_30d / stats.questions_30d) : "—"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Coût total (30j)</span>
              <span className="font-medium">{formatCost(stats.cost_30d)}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
