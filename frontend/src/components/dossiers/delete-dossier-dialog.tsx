"use client";

import { useErrorState } from "@/hooks/use-error-state";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import { dossierChanged, type Dossier } from "@/lib/dossiers-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";

export function DeleteDossierDialog({
  dossier,
  token,
  onClose,
  onDeleted,
}: {
  dossier: Dossier | null;
  token: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const deleting = useRef(false);
  const [error, setError] = useErrorState("");
  useEffect(() => {
    setError("");
  }, [dossier?.id, setError]);
  return (
    <Dialog
      open={!!dossier}
      onOpenChange={(open) => {
        if (!open && !busy) {
          setError("");
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Supprimer le dossier</DialogTitle>
          <DialogDescription>
            Supprimer définitivement « {dossier?.name} » ? Ses conversations,
            ses informations et ses documents privés seront supprimés. Les
            documents de l’entreprise associés seront conservés. Cette action
            est irréversible.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            Annuler
          </Button>
          <Button
            variant="destructive"
            disabled={busy}
            onClick={async () => {
              if (!dossier || deleting.current) return;
              deleting.current = true;
              setBusy(true);
              setError("");
              try {
                await apiFetch<void>(
                  `/dossiers/${dossier.id}?expected_version=${dossier.version}`,
                  { method: "DELETE", token }
                );
                onDeleted();
                onClose();
                dossierChanged();
              } catch (e) {
                setError(
                  e instanceof Error ? e.message : "Suppression impossible"
                );
              } finally {
                deleting.current = false;
                setBusy(false);
              }
            }}
          >
            {busy ? "Suppression…" : "Supprimer définitivement"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
