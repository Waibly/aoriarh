"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ErrorPage {
  items: {
    id: string;
    name: string;
    organisation_id: string | null;
    organisation_name: string | null;
    indexation_error: string | null;
  }[];
  total: number;
  page: number;
  page_size: number;
}

export function IndexationErrors({ token }: { token: string }) {
  const [data, setData] = useState<ErrorPage | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiFetch<ErrorPage>(
        `/admin/documents/errors?page=${page}&page_size=20`, { token },
      );
      if (page > 1 && result.items.length === 0) {
        setPage(1);
      } else {
        setData(result);
      }
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [token, page]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 30000);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <Card id="indexation-errors" className="scroll-mt-6">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">
          Documents en erreur d’indexation{data ? ` (${data.total})` : ""}
        </CardTitle>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          Actualiser
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">Corpus commun et toutes les organisations.</p>
        {error ? (
          <p role="alert" className="text-sm text-destructive">Impossible d’actualiser les erreurs d’indexation.</p>
        ) : !data ? (
          <p className="text-sm">Chargement…</p>
        ) : data.total === 0 ? (
          <p className="text-sm">Aucun document en erreur d’indexation.</p>
        ) : null}
        {data?.items.map((doc) => (
          <div key={doc.id} className="rounded border p-3 space-y-1">
            <p className="font-medium text-sm break-words">{doc.name}</p>
            <p className="text-xs text-muted-foreground">
              {doc.organisation_id ? `Organisation : ${doc.organisation_name ?? doc.organisation_id}` : "Corpus commun"}
            </p>
            <p className="text-sm text-destructive whitespace-pre-wrap break-words">
              {doc.indexation_error ?? "Échec d’indexation sans détail technique enregistré."}
            </p>
          </div>
        ))}
        {data && data.total > data.page_size && (
          <div className="flex items-center gap-3">
            <Button variant="outline" size="sm" disabled={page === 1 || loading} onClick={() => setPage(page - 1)}>Précédent</Button>
            <span className="text-xs">Page {data.page} sur {Math.ceil(data.total / data.page_size)}</span>
            <Button variant="outline" size="sm" disabled={page * data.page_size >= data.total || loading} onClick={() => setPage(page + 1)}>Suivant</Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
