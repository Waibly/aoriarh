"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { Settings2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { getPlanLabel } from "@/lib/plans";
import { cn } from "@/lib/utils";

type ClientRow = {
  account_id: string;
  account_name: string | null;
  owner_email: string | null;
  plan: string;
  status: string;
  mrr_eur: number;
  questions_30d: number;
  infra_cost_eur_30d: number;
  margin_eur: number;
  last_activity_at: string | null;
};

type ClientsResponse = {
  rows: ClientRow[];
  total: number;
  page: number;
  page_size: number;
};

type SortKey = "margin" | "mrr" | "questions" | "activity" | "name";

const SORT_LABELS: Record<SortKey, string> = {
  margin: "Marge",
  mrr: "MRR",
  questions: "Questions (30 j)",
  activity: "Dernière activité",
  name: "Nom",
};

const STATUS_VARIANTS: Record<
  string,
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  trialing: "secondary",
  past_due: "destructive",
  suspended: "destructive",
  canceled: "outline",
};

const fmtEur = (n: number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(
    n
  );

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR") : "—";

export default function AdminClientsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [data, setData] = useState<ClientsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<SortKey>("margin");
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const d = await apiFetch<ClientsResponse>(
        `/admin/business/clients?sort=${sort}&page=${page}&page_size=50`,
        { token }
      );
      setData(d);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Chargement impossible");
    } finally {
      setLoading(false);
    }
  }, [token, sort, page]);

  useEffect(() => {
    load();
  }, [load]);

  const totalPages = data
    ? Math.max(1, Math.ceil(data.total / data.page_size))
    : 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Clients</h1>
          <p className="text-muted-foreground text-sm">
            Plan, revenu, usage et marge par compte (30 derniers jours).
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/admin/users">
            <Settings2 className="mr-2 h-4 w-4" />
            Gérer les comptes
          </Link>
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-muted-foreground text-sm">Trier par</span>
        <Select
          value={sort}
          onValueChange={(v) => {
            setSort(v as SortKey);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
              <SelectItem key={k} value={k}>
                {SORT_LABELS[k]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading && !data ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10" />
              ))}
            </div>
          ) : !data || data.rows.length === 0 ? (
            <p className="text-muted-foreground p-8 text-center text-sm">
              Aucun client.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Client</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Statut</TableHead>
                  <TableHead className="text-right">MRR</TableHead>
                  <TableHead className="text-right">Questions (30 j)</TableHead>
                  <TableHead className="text-right">Coût infra</TableHead>
                  <TableHead className="text-right">Marge</TableHead>
                  <TableHead>Dernière activité</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map((r) => (
                  <TableRow key={r.account_id}>
                    <TableCell>
                      <div className="font-medium">{r.account_name ?? "—"}</div>
                      <div className="text-muted-foreground text-xs">
                        {r.owner_email ?? "—"}
                      </div>
                    </TableCell>
                    <TableCell>{getPlanLabel(r.plan)}</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANTS[r.status] ?? "outline"}>
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtEur(r.mrr_eur)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.questions_30d}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtEur(r.infra_cost_eur_30d)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-medium tabular-nums",
                        r.margin_eur < 0
                          ? "text-destructive"
                          : "text-emerald-600 dark:text-emerald-400"
                      )}
                    >
                      {fmtEur(r.margin_eur)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {fmtDate(r.last_activity_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {data && data.total > data.page_size && (
        <div className="flex items-center justify-between">
          <p className="text-muted-foreground text-sm">
            {data.total} client{data.total > 1 ? "s" : ""}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Précédent
            </Button>
            <span className="text-sm tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Suivant
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
