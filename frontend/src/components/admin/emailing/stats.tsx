"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Eye, Mail, MousePointerClick, RefreshCw, Users } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
  AdminEmptyState,
  AdminLoadError,
} from "@/components/admin/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatsTable, pct } from "./stats-table";
import { STATUS_BADGE, type CampaignStats, type EmailCampaign } from "./types";

export function EmailingStats({
  initialCampaign,
}: {
  initialCampaign?: string;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [selectedId, setSelectedId] = useState(initialCampaign ?? "");
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(false);
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [statsError, setStatsError] = useState(false);
  const [loadingStats, setLoadingStats] = useState(false);
  const [revision, setRevision] = useState(0);

  const loadCampaigns = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setListError(false);
    try {
      const data = await apiFetch<EmailCampaign[]>(
        "/admin/emailing/campaigns",
        { token }
      );
      setCampaigns(data);
      setSelectedId((current) =>
        data.some((c) => c.id === current) ? current : (data[0]?.id ?? "")
      );
    } catch {
      setListError(true);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  useEffect(() => {
    if (!token || !selectedId) return;
    let cancelled = false;
    setLoadingStats(true);
    setStatsError(false);
    setStats(null);
    apiFetch<CampaignStats>(`/admin/emailing/campaigns/${selectedId}/stats`, {
      token,
    })
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch(() => {
        if (!cancelled) setStatsError(true);
      })
      .finally(() => {
        if (!cancelled) setLoadingStats(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, selectedId, revision]);

  function selectCampaign(id: string) {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("campaign", id);
    window.history.replaceState(null, "", url);
  }

  const currentStats = stats?.campaign_id === selectedId ? stats : null;
  const totals = currentStats?.steps.reduce(
    (sum, step) => ({
      sent: sum.sent + step.sent,
      opened: sum.opened + step.opened,
      clicked: sum.clicked + step.clicked,
    }),
    { sent: 0, opened: 0, clicked: 0 }
  );
  const status = currentStats ? STATUS_BADGE[currentStats.status] : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-full space-y-2 sm:w-80">
          <Label htmlFor="emailing-stats-campaign">Campagne à analyser</Label>
          <Select
            value={selectedId}
            onValueChange={selectCampaign}
            disabled={loading || listError || campaigns.length === 0}
          >
            <SelectTrigger id="emailing-stats-campaign" className="w-full">
              <SelectValue placeholder="Choisir une campagne" />
            </SelectTrigger>
            <SelectContent>
              {campaigns.map((campaign) => (
                <SelectItem key={campaign.id} value={campaign.id}>
                  {campaign.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          disabled={loading || loadingStats}
          onClick={() => {
            loadCampaigns();
            setRevision((value) => value + 1);
          }}
        >
          <RefreshCw
            className={
              loading || loadingStats ? "size-4 animate-spin" : "size-4"
            }
          />{" "}
          Actualiser
        </Button>
      </div>
      {listError ? (
        <AdminLoadError
          message="Impossible de charger la liste des campagnes."
          onRetry={loadCampaigns}
        />
      ) : loading || loadingStats ? (
        <div
          role="status"
          aria-label="Chargement des statistiques"
          className="space-y-4"
        >
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-32 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-64 rounded-xl" />
        </div>
      ) : campaigns.length === 0 ? (
        <Card>
          <AdminEmptyState
            title="Vos résultats apparaîtront ici"
            description="Créez votre première campagne pour suivre les envois, les ouvertures et les clics."
            action={
              <Button asChild>
                <Link href="/admin/emailing">Préparer une campagne</Link>
              </Button>
            }
          />
        </Card>
      ) : statsError ? (
        <AdminLoadError
          message="Impossible de charger les statistiques de cette campagne."
          onRetry={() => setRevision((value) => value + 1)}
        />
      ) : currentStats && totals ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight">
              {currentStats.campaign_name}
            </h2>
            <Badge variant={status?.variant ?? "outline"}>
              {status?.label ?? currentStats.status}
            </Badge>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[
              {
                label: "Contacts",
                value: currentStats.total_recipients.toLocaleString("fr-FR"),
                detail: "Destinataires de la campagne",
                icon: Users,
              },
              {
                label: "Emails envoyés",
                value: totals.sent.toLocaleString("fr-FR"),
                detail: "Toutes les étapes de la séquence",
                icon: Mail,
              },
              {
                label: "Taux d’ouverture",
                value: pct(totals.opened, totals.sent),
                detail: `${totals.opened.toLocaleString("fr-FR")} ouvertures`,
                icon: Eye,
              },
              {
                label: "Taux de clic",
                value: pct(totals.clicked, totals.sent),
                detail: `${totals.clicked.toLocaleString("fr-FR")} clics · hors robots`,
                icon: MousePointerClick,
              },
            ].map(({ label, value, detail, icon: Icon }) => (
              <Card key={label}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-muted-foreground text-sm font-medium">
                    {label}
                  </CardTitle>
                  <Icon
                    className="text-muted-foreground size-4"
                    aria-hidden="true"
                  />
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-semibold tabular-nums">{value}</p>
                  <p className="text-muted-foreground mt-1 text-xs">{detail}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">
            Les indicateurs cumulent les étapes de la séquence : un contact peut
            recevoir plusieurs emails. Les taux sont calculés sur les emails
            envoyés.
          </p>
          {totals.sent === 0 && (
            <div className="bg-muted/50 rounded-xl border p-4 text-sm">
              Aucun email envoyé pour le moment. Les résultats se rempliront
              après les premiers envois.
            </div>
          )}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Résultats par email</CardTitle>
              <CardDescription>
                Le détail de chaque étape et de ses relances conditionnelles.
              </CardDescription>
            </CardHeader>
            <CardContent className="min-w-0 px-2 sm:px-6">
              <StatsTable stats={currentStats} />
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
