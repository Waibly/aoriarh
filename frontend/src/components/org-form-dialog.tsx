"use client";

import { useEffect, useState } from "react";
import { Building2, UserCog, ArrowRight, ArrowLeft, Check } from "lucide-react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  FORME_JURIDIQUE_OPTIONS,
  TAILLE_OPTIONS,
  PROFIL_METIER_OPTIONS,
} from "@/types/api";
import type { Organisation } from "@/types/api";

interface OrgFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** If provided, the dialog is in edit mode (no wizard). */
  org?: Organisation | null;
  /** Called with org data. In wizard mode, also receives profil_metier. */
  onSubmit: (data: {
    name: string;
    forme_juridique: string | null;
    taille: string | null;
    convention_collective: string | null;
    secteur_activite: string | null;
    profil_metier?: string | null;
  }) => Promise<void>;
}

export function OrgFormDialog({
  open,
  onOpenChange,
  org,
  onSubmit,
}: OrgFormDialogProps) {
  const isEdit = !!org;

  // Step management (only for create mode)
  const [step, setStep] = useState(1);

  // Org fields
  const [name, setName] = useState("");
  const [formeJuridique, setFormeJuridique] = useState("");
  const [taille, setTaille] = useState("");
  const [conventionCollective, setConventionCollective] = useState("");
  const [secteurActivite, setSecteurActivite] = useState("");

  // User field (step 2)
  const [profilMetier, setProfilMetier] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setStep(1);
      setName(org?.name ?? "");
      setFormeJuridique(org?.forme_juridique ?? "");
      setTaille(org?.taille ?? "");
      setConventionCollective(org?.convention_collective ?? "");
      setSecteurActivite(org?.secteur_activite ?? "");
      setProfilMetier("");
      setError(null);
    }
  }, [open, org]);

  async function handleFinalSubmit() {
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        name: name.trim(),
        forme_juridique: formeJuridique || null,
        taille: taille || null,
        convention_collective: conventionCollective.trim() || null,
        secteur_activite: secteurActivite.trim() || null,
        ...(!isEdit ? { profil_metier: profilMetier || null } : {}),
      });
      onOpenChange(false);
    } catch {
      setError(
        isEdit
          ? "Erreur lors de la modification de l'organisation"
          : "Erreur lors de la création de l'organisation"
      );
    } finally {
      setSubmitting(false);
    }
  }

  // --- Edit mode: single form ---
  if (isEdit) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Modifier l&apos;organisation</DialogTitle>
            <DialogDescription>
              Ces informations permettent d&apos;adapter les réponses juridiques
              aux obligations spécifiques de votre entreprise.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleFinalSubmit();
            }}
            className="space-y-5"
          >
            <OrgFields
              name={name}
              setName={setName}
              formeJuridique={formeJuridique}
              setFormeJuridique={setFormeJuridique}
              taille={taille}
              setTaille={setTaille}
              secteurActivite={secteurActivite}
              setSecteurActivite={setSecteurActivite}
              conventionCollective={conventionCollective}
              setConventionCollective={setConventionCollective}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => onOpenChange(false)}
              >
                Annuler
              </Button>
              <Button type="submit" disabled={submitting || !name.trim()}>
                {submitting ? "Enregistrement..." : "Enregistrer"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    );
  }

  // --- Create mode: 2-step wizard ---
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg gap-0 p-0 overflow-hidden">
        {/* Wizard stepper bar */}
        <div className="flex items-center border-b bg-muted/30 px-6 py-4">
          <StepBadge step={1} current={step} icon={<Building2 className="h-3.5 w-3.5" />} label="Organisation" />
          <div className="mx-3 h-px w-8 bg-border" />
          <StepBadge step={2} current={step} icon={<UserCog className="h-3.5 w-3.5" />} label="Votre profil" />
        </div>

        {/* Step content */}
        <div className="px-6 pt-5 pb-6">
          {step === 1 && (
            <>
              <DialogHeader className="mb-5">
                <DialogTitle>Votre entreprise</DialogTitle>
                <DialogDescription>
                  Ces informations permettent d&apos;adapter les réponses
                  juridiques aux obligations spécifiques de votre entreprise.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-5">
                <OrgFields
                  name={name}
                  setName={setName}
                  formeJuridique={formeJuridique}
                  setFormeJuridique={setFormeJuridique}
                  taille={taille}
                  setTaille={setTaille}
                  secteurActivite={secteurActivite}
                  setSecteurActivite={setSecteurActivite}
                  conventionCollective={conventionCollective}
                  setConventionCollective={setConventionCollective}
                />
                <DialogFooter className="pt-2">
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => onOpenChange(false)}
                  >
                    Annuler
                  </Button>
                  <Button
                    type="button"
                    disabled={!name.trim()}
                    onClick={() => setStep(2)}
                  >
                    Suivant
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </DialogFooter>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <DialogHeader className="mb-5">
                <DialogTitle>Votre profil</DialogTitle>
                <DialogDescription>
                  Votre fonction détermine l&apos;angle des réponses : un élu
                  CSE et un DRH n&apos;ont pas les mêmes besoins juridiques.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-5">
                <div className="space-y-1.5">
                  <Label htmlFor="profil-metier">Quel est votre rôle ?</Label>
                  <Select value={profilMetier} onValueChange={setProfilMetier}>
                    <SelectTrigger id="profil-metier">
                      <SelectValue placeholder="Sélectionner votre profil..." />
                    </SelectTrigger>
                    <SelectContent>
                      {PROFIL_METIER_OPTIONS.map((p) => (
                        <SelectItem key={p.value} value={p.value}>
                          {p.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Vous pourrez modifier ce choix à tout moment dans Mon
                    compte.
                  </p>
                </div>

                {error && (
                  <p className="text-sm text-destructive">{error}</p>
                )}
                <DialogFooter className="pt-2">
                  <Button
                    variant="outline"
                    type="button"
                    onClick={() => setStep(1)}
                  >
                    <ArrowLeft className="mr-2 h-4 w-4" />
                    Retour
                  </Button>
                  <Button
                    type="button"
                    disabled={submitting}
                    onClick={handleFinalSubmit}
                  >
                    {submitting ? "Création..." : "Créer l'organisation"}
                  </Button>
                </DialogFooter>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// --- Wizard step badge ---

function StepBadge({
  step,
  current,
  icon,
  label,
}: {
  step: number;
  current: number;
  icon: React.ReactNode;
  label: string;
}) {
  const isActive = step === current;
  const isDone = step < current;

  return (
    <div
      className={`flex items-center gap-2 rounded-full px-3.5 py-2 text-xs font-semibold transition-all ${
        isActive || isDone
          ? "bg-[#9952b8]/10 text-[#7b2da0]"
          : "bg-muted text-muted-foreground"
      }`}
    >
      {isDone ? <Check className="h-3.5 w-3.5" /> : icon}
      <span>{label}</span>
    </div>
  );
}

// --- Shared org fields ---

function OrgFields({
  name,
  setName,
  formeJuridique,
  setFormeJuridique,
  taille,
  setTaille,
  secteurActivite,
  setSecteurActivite,
  conventionCollective,
  setConventionCollective,
}: {
  name: string;
  setName: (v: string) => void;
  formeJuridique: string;
  setFormeJuridique: (v: string) => void;
  taille: string;
  setTaille: (v: string) => void;
  secteurActivite: string;
  setSecteurActivite: (v: string) => void;
  conventionCollective: string;
  setConventionCollective: (v: string) => void;
}) {
  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="org-name">
          Nom de l&apos;entreprise{" "}
          <span className="text-destructive">*</span>
        </Label>
        <Input
          id="org-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Ex : Waibly SAS"
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="forme-juridique">Forme juridique</Label>
        <Select value={formeJuridique} onValueChange={setFormeJuridique}>
          <SelectTrigger id="forme-juridique">
            <SelectValue placeholder="Sélectionner..." />
          </SelectTrigger>
          <SelectContent>
            {FORME_JURIDIQUE_OPTIONS.map((fj) => (
              <SelectItem key={fj} value={fj}>
                {fj}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="taille">Effectif</Label>
        <Select value={taille} onValueChange={setTaille}>
          <SelectTrigger id="taille">
            <SelectValue placeholder="Nombre de salariés..." />
          </SelectTrigger>
          <SelectContent>
            {TAILLE_OPTIONS.map((t) => (
              <SelectItem key={t} value={t}>
                {t} salariés
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="secteur">Secteur d&apos;activité / code APE</Label>
        <Input
          id="secteur"
          value={secteurActivite}
          onChange={(e) => setSecteurActivite(e.target.value)}
          placeholder="Ex : 62.01Z — Programmation informatique"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="ccn">Convention(s) collective(s)</Label>
        <Input
          id="ccn"
          value={conventionCollective}
          onChange={(e) => setConventionCollective(e.target.value)}
          placeholder="Ex : Métallurgie (IDCC 3248), Syntec (IDCC 1486)"
        />
        <p className="text-xs text-muted-foreground">
          Saisissez le nom et/ou le code IDCC. Plusieurs CCN possibles,
          séparées par des virgules.
        </p>
      </div>
    </>
  );
}
