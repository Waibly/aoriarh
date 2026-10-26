"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { ArrowUpRight, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { formatAdminEur, type AdminClientsResponse } from "@/lib/admin-labels";
import {
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Overview = {
  mrr_eur: number;
  infra_cost_eur_30d: number;
  gross_margin_eur: number;
  infra_pct_of_mrr: number | null;
};

export default function ProfitabilityPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [overview, setOverview] = useState<Overview | null>(null);
  const [clients, setClients] = useState<AdminClientsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const [summary, accounts] = await Promise.all([
        apiFetch<Overview>("/admin/business/overview", { token }),
        apiFetch<AdminClientsResponse>(
          "/admin/business/clients?sort=margin&direction=asc&page_size=10",
          { token }
        ),
      ]);
      setOverview(summary);
      setClients(accounts);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [token]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Pilotage"
        title="Rentabilité"
        description="Comparez le revenu récurrent et les coûts IA pour comprendre la marge de votre activité."
        actions={
          <Button variant="outline" disabled={loading} onClick={load}>
            <RefreshCw className="size-4" />
            Actualiser
          </Button>
        }
      />
      <div className="bg-primary/5 border-primary/10 rounded-xl border px-4 py-3 text-sm">
        Référence : <strong>30 derniers jours</strong> pour les coûts · Revenu
        récurrent mensuel · Tous les montants en euros
      </div>
      {error ? (
        <AdminLoadError onRetry={load} />
      ) : loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : (
        overview && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  title: "Revenu mensuel",
                  value: formatAdminEur(overview.mrr_eur),
                  detail: "Abonnements ramenés au mois",
                },
                {
                  title: "Coûts IA",
                  value: formatAdminEur(overview.infra_cost_eur_30d),
                  detail: "Questions et ingestions sur 30 jours",
                },
                {
                  title: "Marge estimée",
                  value: formatAdminEur(overview.gross_margin_eur),
                  detail: "Revenu mensuel − coûts IA sur 30 jours",
                },
                {
                  title: "Part des coûts IA",
                  value:
                    overview.infra_pct_of_mrr === null
                      ? "—"
                      : `${overview.infra_pct_of_mrr} %`,
                  detail: "Coûts IA rapportés au revenu mensuel",
                },
              ].map((item) => (
                <Card key={item.title} className="border shadow-none">
                  <CardHeader>
                    <CardTitle className="text-muted-foreground text-sm font-medium">
                      {item.title}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-2xl font-semibold tabular-nums">
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
              <CardHeader className="flex flex-wrap items-start justify-between gap-3 sm:flex-row">
                <div className="space-y-2">
                  <CardTitle className="text-base">
                    Clients avec la marge la plus faible
                  </CardTitle>
                  <p className="text-muted-foreground text-sm">
                    Les 10 premiers comptes, du moins au plus rentable sur cette
                    base de calcul.
                  </p>
                </div>
                <Button variant="outline" size="sm" asChild>
                  <Link href="/admin/clients">
                    Tous les clients
                    <ArrowUpRight className="size-4" />
                  </Link>
                </Button>
              </CardHeader>
              <CardContent>
                {clients?.rows.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Client</TableHead>
                        <TableHead className="text-right">
                          Revenu / mois
                        </TableHead>
                        <TableHead className="text-right">
                          Coûts IA · 30 j
                        </TableHead>
                        <TableHead className="text-right">
                          Marge estimée
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {clients.rows.map((client) => (
                        <TableRow key={client.account_id}>
                          <TableCell>
                            <Link
                              className="hover:text-primary font-medium hover:underline"
                              href={`/admin/clients/${client.account_id}`}
                            >
                              {client.account_name ||
                                client.owner_email ||
                                "Client"}
                            </Link>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatAdminEur(client.mrr_eur)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatAdminEur(client.infra_cost_eur_30d)}
                          </TableCell>
                          <TableCell
                            className={`text-right tabular-nums ${client.margin_eur < 0 ? "text-destructive" : ""}`}
                          >
                            {formatAdminEur(client.margin_eur)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-muted-foreground py-4 text-sm">
                    Aucun compte à afficher.
                  </p>
                )}
              </CardContent>
            </Card>
            <details className="bg-card rounded-xl border p-5">
              <summary className="cursor-pointer text-sm font-medium">
                Comprendre ces chiffres
              </summary>
              <div className="text-muted-foreground mt-4 space-y-3 text-sm leading-relaxed">
                <p>
                  La marge estimée compare le revenu récurrent mensuel aux coûts
                  IA des 30 derniers jours. Elle ne représente pas un résultat
                  comptable : salaires, hébergement et autres charges fixes ne
                  sont pas déduits.
                </p>
                <p>
                  Les coûts des questions et des ingestions sont inclus. Les
                  tests du bac à sable sont exclus. Les montants fournisseurs
                  sont convertis en euros au taux configuré.
                </p>
                <p>
                  Les essais et comptes gratuits peuvent présenter une marge
                  négative puisqu’ils génèrent des coûts sans revenu récurrent.
                </p>
              </div>
            </details>
            <Button variant="outline" asChild>
              <Link
                href={
                  session?.user?.staff_role === "business"
                    ? "/admin/costs/details"
                    : "/admin/tools?tab=costs"
                }
              >
                Détails fournisseurs & réglages IA
                <ArrowUpRight className="size-4" />
              </Link>
            </Button>
          </>
        )
      )}
    </div>
  );
}
