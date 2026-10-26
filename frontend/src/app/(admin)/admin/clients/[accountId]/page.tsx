"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { ArrowLeft, ArrowUpRight, CalendarDays, Mail } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
  ACCOUNT_STATUS_LABELS,
  formatAdminEur,
  type AdminClient,
  type AdminClientsResponse,
} from "@/lib/admin-labels";
import { getPlanLabel } from "@/lib/plans";
import {
  AdminEmptyState,
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import { ClientAccounts } from "@/components/admin/client-accounts";
import { BillingPanel } from "@/components/admin/billing-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function ClientDetail() {
  const { accountId } = useParams<{ accountId: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: session } = useSession();
  const token = session?.access_token;
  const [client, setClient] = useState<AdminClient | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const listQuery = searchParams.get("list");
  const returnHref = listQuery
    ? `/admin/clients?${listQuery}`
    : "/admin/clients";
  const requestedTab = searchParams.get("tab");
  const tab =
    requestedTab &&
    ["overview", "account", "billing", "data"].includes(requestedTab)
      ? requestedTab
      : "overview";
  const load = useCallback(async () => {
    if (!token) return;
    setError(false);
    setLoading(true);
    try {
      const response = await apiFetch<AdminClientsResponse>(
        `/admin/business/clients?account_id=${encodeURIComponent(accountId)}`,
        { token }
      );
      setClient(response.rows[0] || null);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [token, accountId]);
  useEffect(() => {
    void load();
  }, [load]);
  const date = (value: string | null) =>
    value
      ? new Date(value).toLocaleDateString("fr-FR", {
          day: "numeric",
          month: "long",
          year: "numeric",
        })
      : "Aucune activité enregistrée";

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-3">
        <Link href={returnHref}>
          <ArrowLeft className="size-4" />
          Tous les clients
        </Link>
      </Button>
      {error ? (
        <AdminLoadError onRetry={load} />
      ) : loading ? (
        <div className="space-y-5">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-52 w-full" />
        </div>
      ) : !client ? (
        <AdminEmptyState
          title="Client introuvable"
          description="Ce compte n’existe plus ou n’est pas disponible."
        />
      ) : (
        <>
          <AdminPageHeader
            section="Fiche client"
            title={client.account_name || client.owner_email || "Client"}
            description={client.owner_email || "Compte client"}
            actions={
              <>
                <Badge variant="outline">{getPlanLabel(client.plan)}</Badge>
                <Badge
                  variant={
                    ["past_due", "suspended"].includes(client.status)
                      ? "destructive"
                      : "secondary"
                  }
                >
                  {ACCOUNT_STATUS_LABELS[client.status] || client.status}
                </Badge>
              </>
            }
          />
          <Tabs
            value={tab}
            onValueChange={(value) =>
              router.replace(
                `/admin/clients/${accountId}?tab=${value}${listQuery ? `&list=${encodeURIComponent(listQuery)}` : ""}`,
                {
                  scroll: false,
                }
              )
            }
            className="gap-6"
          >
            <div className="overflow-x-auto">
              <TabsList
                aria-label="Sections de la fiche client"
                variant="line"
                className="h-11 gap-4 border-b"
              >
                <TabsTrigger value="overview">Vue d’ensemble</TabsTrigger>
                <TabsTrigger value="account">Compte & membres</TabsTrigger>
                <TabsTrigger value="billing">Abonnement</TabsTrigger>
                <TabsTrigger value="data">Données & clôture</TabsTrigger>
              </TabsList>
            </div>
            <TabsContent value="overview" className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  {
                    title: "Revenu mensuel",
                    value: formatAdminEur(client.mrr_eur),
                    detail: "Abonnement ramené au mois",
                  },
                  {
                    title: "Questions posées",
                    value: client.questions_30d.toLocaleString("fr-FR"),
                    detail: "30 derniers jours",
                  },
                  {
                    title: "Coûts IA",
                    value: formatAdminEur(client.infra_cost_eur_30d),
                    detail: "Questions et ingestions · 30 jours",
                  },
                  {
                    title: "Marge estimée",
                    value: formatAdminEur(client.margin_eur),
                    detail: "Revenu mensuel − coûts IA sur 30 jours",
                  },
                ].map((item) => (
                  <Card key={item.title} className="border shadow-none">
                    <CardHeader className="pb-0">
                      <CardTitle className="text-muted-foreground text-sm font-medium">
                        {item.title}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-2xl font-semibold tracking-tight tabular-nums">
                        {item.value}
                      </p>
                      <p className="text-muted-foreground mt-2 text-xs">
                        {item.detail}
                      </p>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <Card className="border shadow-none">
                <CardHeader>
                  <CardTitle className="text-base">Repères du compte</CardTitle>
                </CardHeader>
                <CardContent className="grid gap-5 sm:grid-cols-2">
                  <div className="flex gap-3">
                    <Mail className="text-muted-foreground mt-1 size-4" />
                    <div>
                      <p className="text-muted-foreground text-xs">
                        Propriétaire
                      </p>
                      <p className="mt-1 text-sm break-all">
                        {client.owner_email || "Non renseigné"}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <CalendarDays className="text-muted-foreground mt-1 size-4" />
                    <div>
                      <p className="text-muted-foreground text-xs">
                        Inscription
                      </p>
                      <p className="mt-1 text-sm">
                        {date(client.registered_at)}
                      </p>
                    </div>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">
                      Dernière activité sur les 30 derniers jours
                    </p>
                    <p className="mt-1 text-sm">
                      {date(client.last_activity_at)}
                    </p>
                  </div>
                </CardContent>
              </Card>
              {session?.user?.staff_role !== "business" && (
                <Button variant="outline" asChild>
                  <Link
                    href={{
                      pathname: "/admin/quality",
                      query: {
                        account_id: client.account_id,
                        account_name:
                          client.account_name || client.owner_email || "Client",
                        days: "30",
                      },
                    }}
                  >
                    Consulter les conversations
                    <ArrowUpRight className="size-4" />
                  </Link>
                </Button>
              )}
              <p className="text-muted-foreground text-xs">
                La marge est une estimation avant charges fixes. Les coûts
                fournisseurs sont convertis en euros au taux configuré.
              </p>
            </TabsContent>
            <TabsContent value="account">
              <ClientAccounts
                accountId={accountId}
                onChanged={load}
                onDeleted={() => router.replace(returnHref)}
              />
            </TabsContent>
            <TabsContent value="billing">
              <BillingPanel accountId={accountId} />
            </TabsContent>
            <TabsContent value="data">
              <BillingPanel
                accountId={accountId}
                accountName={client.account_name || "compte"}
                lifecycle
                onErased={() => router.replace(returnHref)}
              />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

export default function ClientDetailPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ClientDetail />
    </Suspense>
  );
}
