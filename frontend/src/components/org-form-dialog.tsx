"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PROFIL_METIER_OPTIONS } from "@/types/api";
import type { Organisation, CcnReference } from "@/types/api";
import {
  OrgFormFields,
  emptyOrgFormFields,
  isOrgFormFieldsValid,
  type OrgFormFieldsValues,
} from "@/components/org/org-form-fields";

interface OrgFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** If provided, the dialog is in edit mode (no wizard). */
  org?: Organisation | null;
  /** Called with org data. In wizard mode, also receives profil_metier and selectedCcn. */
  onSubmit: (data: {
    name: string;
    forme_juridique: string | null;
    taille: string | null;
    convention_collective: string | null;
    secteur_activite: string | null;
    not_subject_to_ccn?: boolean;
    profil_metier?: string | null;
    selectedCcn?: CcnReference[];
  }) => Promise<void>;
}

export function OrgFormDialog({
  open,
  onOpenChange,
  org,
  onSubmit,
}: OrgFormDialogProps) {
  const { data: session } = useSession();
  const token = session?.access_token ?? "";
  const isEdit = !!org;

  // Step management (only for create mode)
  const [step, setStep] = useState(1);

  // Org fields
  const [orgValues, setOrgValues] = useState<OrgFormFieldsValues>(
    emptyOrgFormFields(),
  );

  // User field (step 2)
  const [profilMetier, setProfilMetier] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setStep(1);
      setOrgValues({
        name: org?.name ?? "",
        formeJuridique: org?.forme_juridique ?? "",
        taille: org?.taille ?? "",
        secteurActivite: org?.secteur_activite ?? "",
        selectedCcn: [],
        notSubjectToCcn: org?.not_subject_to_ccn ?? false,
      });
      setProfilMetier("");
      setError(null);
    }
  }, [open, org]);

  async function handleFinalSubmit() {
    if (!orgValues.name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const ccnLabel = orgValues.notSubjectToCcn
        ? null
        : orgValues.selectedCcn.length > 0
          ? orgValues.selectedCcn
              .map((c) => `${c.titre_court || c.titre} (IDCC ${c.idcc})`)
              .join(", ")
          : null;
      await onSubmit({
        name: orgValues.name.trim(),
        forme_juridique: orgValues.formeJuridique || null,
        taille: orgValues.taille || null,
        convention_collective: ccnLabel,
        secteur_activite: orgValues.secteurActivite.trim() || null,
        not_subject_to_ccn: orgValues.notSubjectToCcn,
        ...(!isEdit
          ? {
              profil_metier: profilMetier || null,
              selectedCcn: orgValues.notSubjectToCcn ? [] : orgValues.selectedCcn,
            }
          : {}),
      });
      onOpenChange(false);
    } catch (err) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : isEdit
            ? "Impossible de modifier l'organisation. Réessayez ou contactez le support."
            : "Impossible de créer l'organisation. Réessayez ou contactez le support.";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  // --- Edit mode: single form (CCN managed separately on org page) ---
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
            <OrgFormFields
              values={orgValues}
              onChange={setOrgValues}
              token={token}
              hideCcn
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
              <Button type="submit" disabled={submitting || !orgValues.name.trim()}>
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
      <DialogContent className="sm:max-w-xl gap-0 p-0 overflow-hidden max-h-[90vh] flex flex-col">
        {/* Wizard stepper bar */}
        <div className="flex items-center border-b bg-muted/30 px-6 py-4 shrink-0">
          <StepBadge step={1} current={step} icon={<Building2 className="h-3.5 w-3.5" />} label="Organisation" />
          <div className="mx-3 h-px w-8 bg-border" />
          <StepBadge step={2} current={step} icon={<UserCog className="h-3.5 w-3.5" />} label="Votre profil" />
        </div>

        {/* Step content */}
        <div className="px-6 pt-5 pb-6 overflow-y-auto flex-1">
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
                <OrgFormFields
                  values={orgValues}
                  onChange={setOrgValues}
                  token={token}
                  requireTaille
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
                    disabled={!isOrgFormFieldsValid(orgValues, { requireTaille: true })}
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
                  <Label htmlFor="profil-metier">Quel est votre rôle ? <span className="text-destructive">*</span></Label>
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
                    disabled={submitting || !profilMetier}
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
          ? "bg-[#652bb0]/10 text-[#7b2da0]"
          : "bg-muted text-muted-foreground"
      }`}
    >
      {isDone ? <Check className="h-3.5 w-3.5" /> : icon}
      <span>{label}</span>
    </div>
  );
}
