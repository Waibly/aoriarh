"use client";

import { useErrorState } from "@/hooks/use-error-state";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { getConversationCaseFile } from "@/lib/chat-api";
import { dossierChanged, type DossierDetail } from "@/lib/dossiers-api";
import type { ConversationCaseFile } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

export function CreateDossierDialog({
  open,
  onOpenChange,
  organisationId,
  organisationName,
  token,
  conversationId,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organisationId: string;
  organisationName?: string;
  token: string;
  conversationId?: string;
  onCreated?: (d: DossierDetail) => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useErrorState("");
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<ConversationCaseFile | null>(null);
  const [entries, setEntries] = useState<string[]>([]);
  const [documents, setDocuments] = useState<string[]>([]);
  const creationKey = useRef("");
  const submitting = useRef(false);
  useEffect(() => {
    if (!open) return;
    creationKey.current = crypto.randomUUID();
    setError("");
    setContext(null);
    let cancelled = false;
    if (conversationId)
      void getConversationCaseFile(conversationId, token)
        .then((c) => {
          if (cancelled) return;
          setContext(c);
          setEntries(
            c.entries
              .filter(
                (e) =>
                  ["active", "confirmed", "contested"].includes(e.status) &&
                  [
                    "fact",
                    "party_statement",
                    "assumption",
                    "deadline",
                  ].includes(e.entry_type)
              )
              .map((e) => e.id)
          );
          setDocuments(
            c.documents.flatMap((d) => (d.document_id ? [d.document_id] : []))
          );
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    return () => {
      cancelled = true;
    };
  }, [open, conversationId, token, organisationId, setError]);
  const toggle = (id: string, values: string[], set: (v: string[]) => void) =>
    set(values.includes(id) ? values.filter((v) => v !== id) : [...values, id]);
  async function submit() {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const d = await apiFetch<DossierDetail>("/dossiers/", {
        token,
        method: "POST",
        body: JSON.stringify({
          name,
          organisation_id: organisationId,
          creation_key: creationKey.current,
          ...(conversationId
            ? {
                conversation_id: conversationId,
                entry_ids: entries,
                document_ids: documents,
                expected_case_version: context?.version,
              }
            : {}),
        }),
      });
      dossierChanged();
      onOpenChange(false);
      setName("");
      if (onCreated) onCreated(d);
      else router.push(`/dossiers/${d.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Création impossible");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!busy) onOpenChange(v);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Créer un dossier</DialogTitle>
          <DialogDescription>
            Un dossier rassemble les informations, documents et conversations
            d’un sujet RH.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="space-y-4"
        >
          <label className="flex flex-col gap-2 text-sm font-medium">
            <span>Nom du dossier</span>
            <Input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              placeholder="Accord télétravail 2027"
              disabled={busy}
            />
          </label>
          <p className="text-muted-foreground text-xs">
            {organisationName} · Dossier personnel
          </p>
          {conversationId && (
            <div className="max-h-64 space-y-3 overflow-auto rounded-lg border p-3 text-sm">
              <p>
                Cette conversation sera conservée dans le nouveau dossier.
                Choisissez son contexte commun.
              </p>
              {!context && !error && (
                <p role="status">Chargement du contexte…</p>
              )}
              {context?.entries
                .filter(
                  (e) =>
                    ["active", "confirmed", "contested"].includes(e.status) &&
                    [
                      "fact",
                      "party_statement",
                      "assumption",
                      "deadline",
                    ].includes(e.entry_type)
                )
                .map((e) => (
                  <label key={e.id} className="flex gap-2">
                    <input
                      type="checkbox"
                      checked={entries.includes(e.id)}
                      onChange={() => toggle(e.id, entries, setEntries)}
                    />
                    <span>
                      {e.label}
                      <span className="text-muted-foreground block whitespace-pre-wrap">
                        {e.value_text}
                      </span>
                    </span>
                  </label>
                ))}
              {context?.documents
                .filter((d) => d.document_id)
                .map((d) => (
                  <label key={d.id} className="flex gap-2">
                    <input
                      type="checkbox"
                      checked={documents.includes(d.document_id!)}
                      onChange={() =>
                        toggle(d.document_id!, documents, setDocuments)
                      }
                    />
                    {d.document_name}
                  </label>
                ))}
              <p className="text-muted-foreground text-xs">
                Les documents déjà partagés avec l’entreprise conservent leur
                visibilité. Les réponses précédentes restent inchangées.
              </p>
            </div>
          )}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              Annuler
            </Button>
            <Button
              disabled={busy || !name.trim() || (!!conversationId && !context)}
            >
              {busy ? "Création…" : "Créer le dossier"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
