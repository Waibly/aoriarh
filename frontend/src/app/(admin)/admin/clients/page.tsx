"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUpRight, Search, Users } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
  ACCOUNT_STATUS_LABELS,
  formatAdminEur,
  type AdminClientsResponse,
} from "@/lib/admin-labels";
import { getPlanLabel } from "@/lib/plans";
import {
  AdminEmptyState,
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const SORT_OPTIONS = {
  signup: "Derniers inscrits",
  name: "Nom du client",
  activity: "Dernière activité",
  mrr: "Revenu décroissant",
  margin: "Marge décroissante",
  questions: "Usage décroissant",
};

function ClientsContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: session } = useSession();
  const token = session?.access_token;
  const [data, setData] = useState<AdminClientsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState(params.get("q") || "");
  const [query, setQuery] = useState(params.get("q") || "");
  const [status, setStatus] = useState(
    ["active", "trialing", "past_due", "suspended", "canceled"].includes(
      params.get("status") || ""
    )
      ? params.get("status")!
      : "all"
  );
  const [sort, setSort] = useState(
    params.get("sort") && params.get("sort")! in SORT_OPTIONS
      ? params.get("sort")!
      : "signup"
  );
  const [page, setPage] = useState(() => {
    const value = Number(params.get("page"));
    return Number.isInteger(value) && value > 0 ? value : 1;
  });
  const request = useRef(0);

  useEffect(() => {
    const timeout = setTimeout(() => {
      if (search.trim() !== query) {
        setQuery(search.trim());
        setPage(1);
      }
    }, 300);
    return () => clearTimeout(timeout);
  }, [search, query]);

  const load = useCallback(async () => {
    if (!token) return;
    const id = ++request.current;
    setLoading(true);
    setError(false);
    try {
      const params = new URLSearchParams({
        sort,
        page: String(page),
        page_size: "25",
      });
      if (query) params.set("q", query);
      if (status !== "all") params.set("status", status);
      const result = await apiFetch<AdminClientsResponse>(
        `/admin/business/clients?${params}`,
        { token }
      );
      if (id === request.current) setData(result);
    } catch {
      if (id === request.current) setError(true);
    } finally {
      if (id === request.current) setLoading(false);
    }
  }, [token, sort, page, query, status]);
  useEffect(() => {
    void load();
  }, [load]);

  const listParams = new URLSearchParams({ sort, page: String(page) });
  if (query) listParams.set("q", query);
  if (status !== "all") listParams.set("status", status);
  const listQuery = listParams.toString();
  useEffect(() => {
    if (params.toString() !== listQuery)
      router.replace(`/admin/clients?${listQuery}`, { scroll: false });
  }, [listQuery, params, router]);
  const clientHref = (id: string) =>
    `/admin/clients/${id}?list=${encodeURIComponent(listQuery)}`;

  const totalPages = data
    ? Math.max(1, Math.ceil(data.total / data.page_size))
    : 1;
  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Pilotage"
        title="Clients"
        description="Retrouvez un client et accédez à son compte, son abonnement et son activité."
        actions={
          <Button asChild variant="outline">
            <Link href="/admin/users">
              <Users className="size-4" />
              Gestion des membres
            </Link>
          </Button>
        }
      />
      <Card className="border py-0 shadow-none">
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-col gap-3 xl:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search
                aria-hidden="true"
                className="text-muted-foreground absolute top-3 left-3 size-4"
              />
              <Input
                aria-label="Rechercher un client par nom ou email"
                placeholder="Rechercher un client, un email…"
                value={search}
                maxLength={255}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 pl-9"
              />
            </div>
            <Select
              value={status}
              onValueChange={(value) => {
                setStatus(value);
                setPage(1);
              }}
            >
              <SelectTrigger
                aria-label="Statut du client"
                className="h-10 w-full sm:w-52"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les statuts</SelectItem>
                {Object.entries(ACCOUNT_STATUS_LABELS)
                  .filter(([key]) =>
                    [
                      "active",
                      "trialing",
                      "past_due",
                      "suspended",
                      "canceled",
                    ].includes(key)
                  )
                  .map(([key, label]) => (
                    <SelectItem key={key} value={key}>
                      {label}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Select
              value={sort}
              onValueChange={(value) => {
                setSort(value);
                setPage(1);
              }}
            >
              <SelectTrigger
                aria-label="Trier les clients"
                className="h-10 w-full sm:w-52"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(SORT_OPTIONS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <p className="text-muted-foreground text-xs">
            Usage et coûts sur les 30 derniers jours. Revenu récurrent ramené au
            mois. Montants en euros.
          </p>
        </CardContent>
        {error ? (
          <div className="px-5 pb-5">
            <AdminLoadError onRetry={load} />
          </div>
        ) : (
          <div aria-busy={loading}>
            {loading ? (
              <div className="space-y-3 px-5 pb-5">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-14 w-full" />
                ))}
              </div>
            ) : !data?.rows.length ? (
              <AdminEmptyState
                title={
                  query || status !== "all"
                    ? "Aucun client ne correspond"
                    : "Aucun client pour le moment"
                }
                description="Chaque client dispose d’une fiche regroupant son compte et son abonnement."
                action={
                  query || status !== "all" ? (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setSearch("");
                        setQuery("");
                        setStatus("all");
                        setPage(1);
                      }}
                    >
                      Effacer les filtres
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <>
                <div className="divide-y md:hidden">
                  {data.rows.map((client) => (
                    <Link
                      key={client.account_id}
                      href={clientHref(client.account_id)}
                      className="hover:bg-muted/50 focus-visible:outline-primary block space-y-4 px-5 py-5 focus-visible:outline-2"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="font-medium break-words">
                            {client.account_name ||
                              client.owner_email ||
                              "Client sans nom"}
                          </p>
                          <p className="text-muted-foreground mt-1 text-xs break-all">
                            {client.owner_email}
                          </p>
                        </div>
                        <ArrowUpRight
                          aria-hidden="true"
                          className="text-muted-foreground size-4 shrink-0"
                        />
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant={
                            ["past_due", "suspended"].includes(client.status)
                              ? "destructive"
                              : "outline"
                          }
                        >
                          {ACCOUNT_STATUS_LABELS[client.status] ||
                            client.status}
                        </Badge>
                        <span className="text-muted-foreground text-xs">
                          {getPlanLabel(client.plan)}
                        </span>
                      </div>
                      <dl className="grid grid-cols-3 gap-3 text-sm">
                        <div>
                          <dt className="text-muted-foreground text-xs">
                            Revenu / mois
                          </dt>
                          <dd className="mt-1 font-medium tabular-nums">
                            {formatAdminEur(client.mrr_eur)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground text-xs">
                            Questions
                          </dt>
                          <dd className="mt-1 font-medium tabular-nums">
                            {client.questions_30d}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-muted-foreground text-xs">
                            Marge estimée
                          </dt>
                          <dd
                            className={`mt-1 font-medium tabular-nums ${client.margin_eur < 0 ? "text-destructive" : ""}`}
                          >
                            {formatAdminEur(client.margin_eur)}
                          </dd>
                        </div>
                      </dl>
                    </Link>
                  ))}
                </div>
                <div className="hidden md:block">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="pl-5">Client</TableHead>
                        <TableHead>Statut</TableHead>
                        <TableHead>Offre</TableHead>
                        <TableHead className="text-right">
                          Revenu / mois
                        </TableHead>
                        <TableHead className="text-right">Questions</TableHead>
                        <TableHead className="text-right">
                          Marge estimée
                        </TableHead>
                        <TableHead className="pr-5">
                          <span className="sr-only">Fiche client</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.rows.map((client) => (
                        <TableRow key={client.account_id} className="group">
                          <TableCell className="pl-5">
                            <Link
                              href={clientHref(client.account_id)}
                              className="text-foreground hover:text-primary font-medium underline-offset-4 hover:underline"
                            >
                              {client.account_name ||
                                client.owner_email ||
                                "Client sans nom"}
                            </Link>
                            <p className="text-muted-foreground mt-1 text-xs">
                              {client.owner_email}
                            </p>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={
                                ["past_due", "suspended"].includes(
                                  client.status
                                )
                                  ? "destructive"
                                  : "outline"
                              }
                            >
                              {ACCOUNT_STATUS_LABELS[client.status] ||
                                client.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-sm">
                            {getPlanLabel(client.plan)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {formatAdminEur(client.mrr_eur)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {client.questions_30d.toLocaleString("fr-FR")}
                          </TableCell>
                          <TableCell
                            className={`text-right tabular-nums ${client.margin_eur < 0 ? "text-destructive" : ""}`}
                          >
                            {formatAdminEur(client.margin_eur)}
                          </TableCell>
                          <TableCell className="pr-5 text-right">
                            <Button variant="ghost" size="icon" asChild>
                              <Link
                                href={clientHref(client.account_id)}
                                aria-label={`Ouvrir la fiche de ${client.account_name || client.owner_email}`}
                              >
                                <ArrowUpRight className="size-4" />
                              </Link>
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </div>
        )}
        {data && !loading && !error && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4">
            <p role="status" className="text-muted-foreground text-sm">
              {data.total} client{data.total > 1 ? "s" : ""}
              {data.total > 0 && ` · Page ${page} sur ${totalPages}`}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((value) => value - 1)}
              >
                Précédent
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((value) => value + 1)}
              >
                Suivant
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function AdminClientsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ClientsContent />
    </Suspense>
  );
}
