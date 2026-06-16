"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Play, FlaskConical, Search } from "lucide-react";
import { InspectorBody, type InspectorPayload, type RagTrace, type CitedSource } from "./InspectorBody";

interface OrgItem {
  id: string;
  name: string;
}

interface SandboxResponse {
  answer: string | null;
  sources: CitedSource[];
  rag_trace: RagTrace;
  cost_usd: number;
  duration_ms: number;
}

export interface SandboxRunnerHandle {
  prefillAndRun: (messageId: string) => void;
}

export function SandboxRunner({
  prefilledQuery,
  prefilledOrgId,
  replayMessageId,
  onConsumed,
}: {
  prefilledQuery?: string;
  prefilledOrgId?: string;
  replayMessageId?: string;
  onConsumed?: () => void;
}) {
  const { data: session } = useSession();
  const [orgs, setOrgs] = useState<OrgItem[]>([]);
  const [orgsLoading, setOrgsLoading] = useState(true);
  const [orgFilter, setOrgFilter] = useState("");
  const [selectedOrgId, setSelectedOrgId] = useState<string>("");
  const [query, setQuery] = useState("");
  const [skipGen, setSkipGen] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SandboxResponse | null>(null);

  // Load orgs once
  useEffect(() => {
    if (!session?.access_token) return;
    apiFetch<OrgItem[]>("/admin/quality/sandbox/organisations", {
      token: session.access_token,
    })
      .then(setOrgs)
      .catch((err) => {
        console.error(err);
        toast.error("Impossible de charger la liste des organisations");
      })
      .finally(() => setOrgsLoading(false));
  }, [session?.access_token]);

  // Handle pre-fill from "Rejouer"
  const runReplay = useCallback(
    async (messageId: string) => {
      if (!session?.access_token) return;
      setRunning(true);
      setResult(null);
      try {
        const data = await apiFetch<SandboxResponse>(
          `/admin/quality/sandbox/replay/${messageId}`,
          {
            method: "POST",
            token: session.access_token,
          },
        );
        setResult(data);
        // Try to populate the form for further iteration
        if (data.rag_trace.query_original) setQuery(data.rag_trace.query_original);
      } catch (err) {
        console.error(err);
        toast.error("Échec du replay");
      } finally {
        setRunning(false);
      }
    },
    [session?.access_token],
  );

  useEffect(() => {
    if (replayMessageId) {
      runReplay(replayMessageId);
      onConsumed?.();
    }
  }, [replayMessageId, runReplay, onConsumed]);

  useEffect(() => {
    if (prefilledQuery) setQuery(prefilledQuery);
  }, [prefilledQuery]);
  useEffect(() => {
    if (prefilledOrgId) setSelectedOrgId(prefilledOrgId);
  }, [prefilledOrgId]);

  const handleRun = async () => {
    if (!session?.access_token) return;
    if (!selectedOrgId) {
      toast.error("Sélectionne une organisation");
      return;
    }
    if (!query.trim()) {
      toast.error("Saisis une question");
      return;
    }
    setRunning(true);
    setResult(null);
    try {
      const data = await apiFetch<SandboxResponse>("/admin/quality/sandbox/run", {
        method: "POST",
        token: session.access_token,
        body: JSON.stringify({
          query: query.trim(),
          organisation_id: selectedOrgId,
          skip_generation: skipGen,
        }),
        headers: { "Content-Type": "application/json" },
      });
      setResult(data);
    } catch (err) {
      console.error(err);
      toast.error("Échec de l'exécution sandbox");
    } finally {
      setRunning(false);
    }
  };

  const filteredOrgs = orgs.filter(
    (o) =>
      !orgFilter.trim() || o.name.toLowerCase().includes(orgFilter.toLowerCase()),
  );

  // Build payload for InspectorBody
  const inspectorData: InspectorPayload | null = result
    ? {
        question: query,
        answer: result.answer,
        sources: result.sources,
        rag_trace: result.rag_trace,
        cost_usd: result.cost_usd,
        latency_ms: result.duration_ms,
      }
    : null;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base font-semibold flex items-center gap-2">
            <FlaskConical className="h-4 w-4" />
            Bac à sable
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Teste une question avec le pipeline RAG actuel sans facturer le
            client ni laisser de trace dans son historique.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Organisation</Label>
              <div className="relative mt-1">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
                <Input
                  placeholder="Filtrer par nom..."
                  value={orgFilter}
                  onChange={(e) => setOrgFilter(e.target.value)}
                  className="pl-7 h-8 text-xs mb-1"
                />
              </div>
              <Select
                value={selectedOrgId}
                onValueChange={setSelectedOrgId}
                disabled={orgsLoading}
              >
                <SelectTrigger>
                  <SelectValue placeholder={orgsLoading ? "Chargement..." : "Sélectionne une org"} />
                </SelectTrigger>
                <SelectContent>
                  {filteredOrgs.length === 0 ? (
                    <div className="px-2 py-1.5 text-xs text-muted-foreground">
                      Aucune org
                    </div>
                  ) : (
                    filteredOrgs.map((o) => (
                      <SelectItem key={o.id} value={o.id}>
                        {o.name}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipGen}
                  onChange={(e) => setSkipGen(e.target.checked)}
                  className="rounded"
                />
                Recherche seulement (sans appel LLM, plus rapide et gratuit)
              </label>
            </div>
          </div>

          <div>
            <Label className="text-xs">Question à tester</Label>
            <Textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={4}
              className="mt-1 text-sm"
              placeholder="Que dit l'article L4121-1 du code du travail ?"
            />
          </div>

          <div className="flex justify-end">
            <Button onClick={handleRun} disabled={running}>
              <Play className="h-4 w-4 mr-2" />
              {running ? "Exécution..." : "Lancer le test"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {running && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-32 w-full" />
            <Skeleton className="h-40 w-full" />
          </CardContent>
        </Card>
      )}

      {!running && inspectorData && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base font-semibold">Résultat</CardTitle>
          </CardHeader>
          <CardContent>
            <InspectorBody data={inspectorData} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
