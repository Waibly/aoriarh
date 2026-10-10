"use client";
import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { apiFetch } from "@/lib/api";

type Incident = {id: string; created: number; state: string; attempts: number; last_error: string | null; payload: Record<string, string | number>};
type Result = {configured: boolean; counts: Record<string, number>; items: Incident[]};
export default function IncidentsPage() {
  const {data: session} = useSession();
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const load = useCallback(async () => {
    if (!session?.access_token) return;
    try {
      setResult(await apiFetch<Result>(`/telemetry/admin/incidents?offset=${offset}`, {token:session.access_token}));
      setError("");
    } catch { setError("Impossible de charger les incidents."); }
  }, [session?.access_token,offset]);
  useEffect(() => { void load(); const id = setInterval(load, 30000); return () => clearInterval(id); }, [load]);
  return <main className="space-y-6 p-6">
    <h1 className="text-2xl font-semibold">Incidents et livraison Slack</h1>
    <p>Chaque incident conserve uniquement des métadonnées techniques. « Accepté par Slack » ne signifie pas qu’une personne l’a lu.</p>
    {error && <p role="alert">{error}</p>}
    {result && !result.configured && <p role="alert">Collecte non configurée.</p>}
    <p>En attente : {result?.counts.pending || 0} · Échecs de livraison : {result?.counts.failed || 0} · Acceptés par Slack : {result?.counts.delivered || 0}</p>
    <button onClick={() => void load()} className="rounded border px-3 py-2">Actualiser</button>
    {result?.items.map(item => <article key={item.id} className="space-y-2 rounded border p-4">
      <h2 className="font-semibold">{item.payload.source} — {item.payload.code}</h2>
      <p>{new Date(item.created*1000).toLocaleString("fr-FR")} · {item.id}</p>
      <p>{item.state === "delivered" ? "Accepté par Slack" : item.state === "failed" ? "Échec de livraison" : "En attente"} · {item.attempts} tentative(s) {item.last_error}</p>
      <dl>{Object.entries(item.payload).map(([key,value]) => <div key={key} className="flex gap-2"><dt>{key} :</dt><dd>{value}</dd></div>)}</dl>
      {item.state === "failed" && <button className="rounded border px-3 py-2" onClick={async () => {
        try { await apiFetch(`/telemetry/admin/incidents/${item.id}/retry`, {method:"POST",token:session?.access_token}); await load(); }
        catch { setError("La remise en file a échoué."); }
      }}>Réessayer l’envoi Slack</button>}
    </article>)}
    <div className="flex gap-4"><button disabled={!offset} onClick={() => setOffset(Math.max(0,offset-100))}>Précédents</button><button disabled={(result?.items.length || 0)<100} onClick={() => setOffset(offset+100)}>Suivants</button></div>
  </main>;
}
