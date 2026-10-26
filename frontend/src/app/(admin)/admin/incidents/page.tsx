"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { AlertTriangle, Bell, RefreshCw } from "lucide-react";
import { apiFetch } from "@/lib/api";
import {
  AdminEmptyState,
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import { ServiceNav } from "@/components/admin/section-nav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Incident = {
  id: string;
  created: number;
  state: string;
  attempts: number;
  last_error: string | null;
  payload: Record<string, string | number>;
};
type Result = {
  configured: boolean;
  counts: Record<string, number>;
  items: Incident[];
};
const CODES: Record<string, string> = {
  http_error: "Erreur de requête",
  ui_error: "Erreur d’interface",
  react_error: "Erreur d’affichage",
  stream_error: "Réponse interrompue",
  stream_incomplete: "Flux de réponse incomplet",
  request_timeout: "Délai de requête dépassé",
  stream_parse_error: "Erreur de lecture du flux",
  turnstile_error: "Erreur de vérification",
  turnstile_timeout: "Délai de vérification dépassé",
};
const DELIVERY: Record<string, string> = {
  delivered: "Accepté par Slack",
  failed: "Échec d’envoi",
  pending: "En attente",
};

export default function IncidentsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [retryError, setRetryError] = useState("");
  const request = useRef(0);
  const load = useCallback(async () => {
    if (!token) return;
    const id = ++request.current;
    try {
      const response = await apiFetch<Result>(
        `/telemetry/admin/incidents?offset=${offset}`,
        { token }
      );
      if (id === request.current) {
        setResult(response);
        setError(false);
      }
    } catch {
      if (id === request.current) setError(true);
    } finally {
      if (id === request.current) setLoading(false);
    }
  }, [token, offset]);
  useEffect(() => {
    setLoading(true);
    void load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);
  const retry = async (id: string) => {
    if (!token) return;
    setRetrying(id);
    setRetryError("");
    try {
      await apiFetch(`/telemetry/admin/incidents/${id}/retry`, {
        method: "POST",
        token,
      });
      await load();
    } catch {
      setRetryError("La remise en file a échoué. Vous pouvez réessayer.");
    } finally {
      setRetrying(null);
    }
  };
  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Exploitation"
        title="Journal des incidents"
        description="Consultez les événements techniques et vérifiez l’envoi de leurs notifications."
        actions={
          <Button variant="outline" size="sm" onClick={load}>
            <RefreshCw className="size-4" />
            Actualiser
          </Button>
        }
      />
      <ServiceNav />
      {error && (
        <AdminLoadError
          message="Impossible d’actualiser les incidents. Les données déjà affichées peuvent être anciennes."
          onRetry={load}
        />
      )}
      {result && !result.configured && (
        <p
          role="alert"
          className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
        >
          La collecte des incidents n’est pas configurée.
        </p>
      )}
      <Tabs defaultValue="events" className="gap-5">
        <TabsList aria-label="Journal des incidents">
          <TabsTrigger value="events">
            <AlertTriangle className="size-4" />
            Événements
          </TabsTrigger>
          <TabsTrigger value="notifications">
            <Bell className="size-4" />
            Notifications Slack
          </TabsTrigger>
        </TabsList>
        <TabsContent value="events" className="space-y-4">
          <p className="text-muted-foreground text-sm">
            Événements enregistrés, du plus récent au plus ancien. Ce journal ne
            suit pas leur résolution.
          </p>
          {loading ? (
            <Skeleton className="h-48 w-full" />
          ) : result?.items.length ? (
            result.items.map((item) => (
              <Card key={item.id} className="gap-3 border py-4 shadow-none">
                <CardHeader>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">
                      {CODES[String(item.payload.code)] ||
                        item.payload.code ||
                        "Événement technique"}
                    </CardTitle>
                    <span className="text-muted-foreground text-xs">
                      {new Date(item.created * 1000).toLocaleString("fr-FR")}
                    </span>
                  </div>
                  <p className="text-muted-foreground text-xs">
                    Source : {item.payload.source || "non renseignée"}
                  </p>
                </CardHeader>
                <CardContent>
                  <details className="text-sm">
                    <summary className="text-muted-foreground cursor-pointer">
                      Détails techniques
                    </summary>
                    <dl className="mt-3 grid gap-2 text-xs">
                      <div>
                        <dt className="text-muted-foreground">
                          Identifiant de l’événement
                        </dt>
                        <dd className="mt-1 font-mono break-all">{item.id}</dd>
                      </div>
                      {Object.entries(item.payload).map(([key, value]) => (
                        <div key={key}>
                          <dt className="text-muted-foreground">{key}</dt>
                          <dd className="mt-1 break-words whitespace-pre-wrap">
                            {value}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                </CardContent>
              </Card>
            ))
          ) : (
            result &&
            !error && (
              <AdminEmptyState
                title="Aucun événement enregistré sur cette page"
                description="Le journal présentera les incidents techniques collectés par l’application."
              />
            )
          )}
        </TabsContent>
        <TabsContent value="notifications" className="space-y-5">
          <p className="text-muted-foreground text-sm">
            Ces statuts décrivent l’envoi des notifications. « Accepté par Slack
            » ne signifie pas qu’une personne a lu ou résolu l’incident.
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            {["pending", "failed", "delivered"].map((state) => (
              <Card key={state} className="gap-3 border py-4 shadow-none">
                <CardHeader>
                  <CardTitle className="text-muted-foreground text-sm font-medium">
                    {DELIVERY[state]}
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-2xl font-semibold tabular-nums">
                  {result ? result.counts[state] || 0 : "—"}
                </CardContent>
              </Card>
            ))}
          </div>
          <p className="text-muted-foreground text-xs">
            Compteurs globaux d’envoi · Détail de la page courante ci-dessous
          </p>
          {retryError && (
            <p role="alert" className="text-destructive text-sm">
              {retryError}
            </p>
          )}
          {loading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            result?.items.map((item) => (
              <div
                key={item.id}
                className="bg-card flex flex-wrap items-center gap-3 rounded-xl border p-4"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {CODES[String(item.payload.code)] ||
                      item.payload.code ||
                      "Événement"}
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {new Date(item.created * 1000).toLocaleString("fr-FR")} ·{" "}
                    {item.attempts} tentative(s)
                  </p>
                  {item.last_error && (
                    <p className="text-destructive mt-2 text-xs break-words">
                      {item.last_error}
                    </p>
                  )}
                </div>
                <Badge
                  variant={item.state === "failed" ? "destructive" : "outline"}
                >
                  {DELIVERY[item.state] || item.state}
                </Badge>
                {item.state === "failed" && (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={retrying !== null}
                    onClick={() => retry(item.id)}
                  >
                    {retrying === item.id
                      ? "Remise en file…"
                      : "Réessayer l’envoi"}
                  </Button>
                )}
              </div>
            ))
          )}
        </TabsContent>
      </Tabs>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <p className="text-muted-foreground text-xs">
          Actualisation toutes les 30 secondes · Page{" "}
          {Math.floor(offset / 100) + 1}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!offset || loading}
            onClick={() => setOffset((value) => Math.max(0, value - 100))}
          >
            Précédent
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!result || result.items.length < 100 || loading || error}
            onClick={() => setOffset((value) => value + 100)}
          >
            Suivant
          </Button>
        </div>
      </div>
    </div>
  );
}
