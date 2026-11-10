"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { apiFetch } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InfoTooltip } from "@/components/admin/info-tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type TrialFeedbackRow = {
  id: string;
  reason: string;
  reason_label: string;
  comment: string | null;
  questions_used: number;
  responded_at: string;
  account_id: string | null;
  account_name: string | null;
  owner_email: string | null;
};

type TrialFeedbackResponse = {
  total: number;
  by_reason: { reason: string; label: string; count: number }[];
  rows: TrialFeedbackRow[];
};

const date = (value: string) =>
  new Date(value).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

/**
 * Réponses au questionnaire envoyé 3 jours après un essai non converti.
 * Sans `accountId` : synthèse et dernières réponses (pilotage).
 * Avec `accountId` : la réponse de ce compte, rien si aucune.
 */
export function TrialFeedbackCard({ accountId }: { accountId?: string }) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [data, setData] = useState<TrialFeedbackResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const query = accountId
      ? `?account_id=${encodeURIComponent(accountId)}`
      : "?limit=20";
    apiFetch<TrialFeedbackResponse>(`/admin/business/trial-feedback${query}`, {
      token,
    })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [token, accountId]);

  if (accountId) {
    const row = data?.rows[0];
    if (!row) return null;
    return (
      <Card className="border shadow-none">
        <CardHeader>
          <CardTitle className="text-base">Réponse de fin d’essai</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="font-medium">{row.reason_label}</span>
            <span className="text-muted-foreground">
              {" "}
              · {date(row.responded_at)} · {row.questions_used} question
              {row.questions_used > 1 ? "s" : ""} pendant l’essai
            </span>
          </p>
          {row.comment && (
            <p className="text-muted-foreground whitespace-pre-wrap">
              {row.comment}
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-1.5 text-sm font-medium">
          Pourquoi les essais ne souscrivent pas{" "}
          <span className="text-muted-foreground font-normal">
            ({data?.total ?? 0} réponse{(data?.total ?? 0) > 1 ? "s" : ""})
          </span>
          <InfoTooltip>
            Réponses à la question envoyée par email 3 jours après la fin d’un
            essai non converti. Après la suppression du compte (30 jours après
            l’essai), la réponse est conservée sans nom ni email.
          </InfoTooltip>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <p className="text-muted-foreground text-sm">
            Impossible de charger les réponses.
          </p>
        )}
        {data && data.total === 0 && (
          <p className="text-muted-foreground py-2 text-sm">
            Aucune réponse pour le moment.
          </p>
        )}
        {data && data.total > 0 && (
          <>
            <div className="space-y-2">
              {data.by_reason.map((r) => {
                const pct = Math.round((r.count / data.total) * 100);
                return (
                  <div key={r.reason} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
                    <span>{r.label}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {r.count} · {pct} %
                    </span>
                    <div className="bg-muted col-span-2 h-1.5 overflow-hidden rounded-full">
                      <div
                        className="bg-primary h-full rounded-full"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Client</TableHead>
                  <TableHead>Raison</TableHead>
                  <TableHead>Commentaire</TableHead>
                  <TableHead className="text-right">Questions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="whitespace-nowrap">
                      {date(row.responded_at)}
                    </TableCell>
                    <TableCell>
                      {row.account_id ? (
                        <Link
                          href={`/admin/clients/${row.account_id}`}
                          className="text-primary hover:underline"
                        >
                          {row.account_name || row.owner_email || "Client"}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">
                          Compte supprimé
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{row.reason_label}</TableCell>
                    <TableCell className="text-muted-foreground max-w-md whitespace-pre-wrap">
                      {row.comment ?? "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.questions_used}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
