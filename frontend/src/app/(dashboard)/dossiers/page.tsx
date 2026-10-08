"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import { FolderOpen, Plus, Pin } from "lucide-react";
import { useOrg } from "@/lib/org-context";
import { listDossiers, type Dossier } from "@/lib/dossiers-api";
import { CreateDossierDialog } from "@/components/dossiers/create-dossier-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function DossiersPage() {
  const { currentOrg } = useOrg();
  const organisationId = currentOrg?.id;
  const { data: session } = useSession();
  const token = session?.access_token;
  const [create, setCreate] = useState(false);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Dossier[]>([]);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setOffset(0);
  }, [organisationId, search]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setRows([]);
    if (!token || !organisationId) return;
    void listDossiers(organisationId, token, false, search, offset)
      .then((r) => {
        if (!cancelled) {
          setRows(r.items);
          setMore(r.has_more);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, organisationId, search, offset, revision]);
  if (!currentOrg)
    return <p>Sélectionnez une organisation pour accéder à vos dossiers.</p>;
  return (
    <section className="flex min-h-0 flex-1 flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dossiers</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Retrouvez les documents et les échanges de vos sujets RH.
          </p>
        </div>
        <Button onClick={() => setCreate(true)} disabled={!token}>
          <Plus className="size-4" />
          Créer un dossier
        </Button>
      </header>
      <div className="dark:bg-card flex-1 space-y-6 rounded-xl bg-white p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(query);
            }}
          >
            <Input
              aria-label="Rechercher un dossier"
              placeholder="Rechercher un dossier"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button variant="outline">Rechercher</Button>
          </form>
        </div>
        {loading ? (
          <p role="status">Chargement des dossiers…</p>
        ) : error ? (
          <div role="alert">
            <p className="text-destructive">{error}</p>
            <Button
              className="mt-3"
              variant="outline"
              onClick={() => setRevision((v) => v + 1)}
            >
              Réessayer
            </Button>
          </div>
        ) : rows.length ? (
          <div className="divide-y rounded-xl border">
            {rows.map((d) => (
              <Link
                key={d.id}
                href={`/dossiers/${d.id}`}
                className="hover:bg-accent/40 flex items-start gap-4 p-4 transition-colors"
              >
                <FolderOpen className="text-primary mt-1 size-5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 font-medium">
                    {d.name}
                    {d.pinned && (
                      <Pin aria-label="Épinglé" className="size-3.5" />
                    )}
                  </p>
                  {d.description && (
                    <p className="text-muted-foreground mt-1 text-sm whitespace-pre-wrap">
                      {d.description}
                    </p>
                  )}
                  <p className="text-muted-foreground mt-2 text-xs">
                    {d.conversation_count} conversation(s) · {d.document_count}{" "}
                    document(s) ·{" "}
                    {new Date(d.updated_at).toLocaleDateString("fr-FR")}
                  </p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed py-14 text-center">
            <FolderOpen className="text-muted-foreground mx-auto mb-4 size-8" />
            <p>
              {search
                ? "Aucun dossier ne correspond à votre recherche."
                : "Rassemblez vos informations et vos échanges autour d’un sujet RH."}
            </p>
            {!search && (
              <Button className="mt-5" onClick={() => setCreate(true)}>
                Créer mon premier dossier
              </Button>
            )}
          </div>
        )}
        {(offset > 0 || more) && (
          <div className="flex justify-between">
            <Button
              variant="outline"
              disabled={!offset || loading}
              onClick={() => setOffset((v) => Math.max(0, v - 50))}
            >
              Précédents
            </Button>
            <Button
              variant="outline"
              disabled={!more || loading}
              onClick={() => setOffset((v) => v + 50)}
            >
              Suivants
            </Button>
          </div>
        )}
      </div>
      {token && (
        <CreateDossierDialog
          open={create}
          onOpenChange={setCreate}
          organisationId={currentOrg.id}
          organisationName={currentOrg.name}
          token={token}
        />
      )}
    </section>
  );
}
