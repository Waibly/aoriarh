"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Document } from "@/types/api";

/** Strip technical markers appended by ingestion (same helper as in page.tsx). */
function cleanDocName(name: string): string {
  return name
    .replace(/\s*\(reingestion [^)]+\)/gi, "")
    .replace(/\s*\(reindex [^)]+\)/gi, "")
    .trim();
}

/**
 * Dialog to edit the user-facing metadata of a document. Does not relaunch
 * indexation — the file content is left untouched.
 *
 * For jurisprudence sources (cassation / cour d'appel / conseil constit),
 * a richer form is shown with juridiction, chambre, formation, etc.
 */
export function MetadataEditDialog({
  doc,
  onClose,
  onSave,
}: {
  doc: Document | null;
  onClose: () => void;
  onSave: (data: Record<string, string | null>) => Promise<void>;
}) {
  const isJurisprudence = doc
    ? /arret|cassation|appel|constit/i.test(doc.source_type)
    : false;

  const [name, setName] = useState("");
  const [juridiction, setJuridiction] = useState("");
  const [chambre, setChambre] = useState("");
  const [formation, setFormation] = useState("");
  const [numeroPourvoi, setNumeroPourvoi] = useState("");
  const [dateDecision, setDateDecision] = useState("");
  const [solution, setSolution] = useState("");
  const [publication, setPublication] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!doc) return;
    setName(cleanDocName(doc.name));
    setJuridiction(doc.juridiction ?? "");
    setChambre(doc.chambre ?? "");
    setFormation(doc.formation ?? "");
    setNumeroPourvoi(doc.numero_pourvoi ?? "");
    setDateDecision(doc.date_decision ?? "");
    setSolution(doc.solution ?? "");
    setPublication(doc.publication ?? "");
  }, [doc]);

  const submit = async () => {
    if (!doc) return;
    setSaving(true);
    const payload: Record<string, string | null> = { name: name.trim() || doc.name };
    if (isJurisprudence) {
      payload.juridiction = juridiction.trim() || null;
      payload.chambre = chambre.trim() || null;
      payload.formation = formation.trim() || null;
      payload.numero_pourvoi = numeroPourvoi.trim() || null;
      payload.date_decision = dateDecision.trim() || null;
      payload.solution = solution.trim() || null;
      payload.publication = publication.trim() || null;
    }
    await onSave(payload);
    setSaving(false);
  };

  return (
    <Dialog open={!!doc} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>Modifier les métadonnées</DialogTitle>
          <DialogDescription>
            Les changements ne relancent pas l&apos;indexation du document. Le fichier lui-même n&apos;est pas modifié.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div>
            <Label htmlFor="meta-name">Nom</Label>
            <Input
              id="meta-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {isJurisprudence && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="meta-juridiction">Juridiction</Label>
                  <Input
                    id="meta-juridiction"
                    value={juridiction}
                    onChange={(e) => setJuridiction(e.target.value)}
                    placeholder="ex. Cour de cassation"
                  />
                </div>
                <div>
                  <Label htmlFor="meta-chambre">Chambre</Label>
                  <Input
                    id="meta-chambre"
                    value={chambre}
                    onChange={(e) => setChambre(e.target.value)}
                    placeholder="ex. soc, cr, civ2"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="meta-formation">Formation</Label>
                  <Input
                    id="meta-formation"
                    value={formation}
                    onChange={(e) => setFormation(e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="meta-numero">N° de pourvoi</Label>
                  <Input
                    id="meta-numero"
                    value={numeroPourvoi}
                    onChange={(e) => setNumeroPourvoi(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="meta-date">Date de décision</Label>
                  <Input
                    id="meta-date"
                    type="date"
                    value={dateDecision}
                    onChange={(e) => setDateDecision(e.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="meta-publi">Publication</Label>
                  <Input
                    id="meta-publi"
                    value={publication}
                    onChange={(e) => setPublication(e.target.value)}
                    placeholder="ex. B, P, R"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="meta-solution">Solution</Label>
                <Input
                  id="meta-solution"
                  value={solution}
                  onChange={(e) => setSolution(e.target.value)}
                  placeholder="ex. rejet, cassation"
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Annuler
          </Button>
          <Button onClick={submit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Enregistrer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
