"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { FORME_JURIDIQUE_OPTIONS, TAILLE_OPTIONS } from "@/types/api";
import type { CcnReference } from "@/types/api";
import { CcnSelector } from "@/components/ccn-selector";

/** Sentinelle du choix « Non précisé » : Radix interdit une SelectItem à valeur
 *  vide, mais on veut stocker taille = "" (→ envoyé comme null au backend, non
 *  transmis au moteur RAG). Ne jamais persister cette valeur. */
const TAILLE_NON_PRECISE = "__non_precise__";

export interface OrgFormFieldsValues {
  name: string;
  formeJuridique: string;
  taille: string;
  secteurActivite: string;
  selectedCcn: CcnReference[];
  notSubjectToCcn: boolean;
}

interface OrgFormFieldsProps {
  values: OrgFormFieldsValues;
  onChange: (next: OrgFormFieldsValues) => void;
  /** Auth token used by the CCN selector to query the API. */
  token: string;
  /** When true, hides the CCN selector and the "not subject" checkbox (edit mode). */
  hideCcn?: boolean;
  /** When true, effectif is required (*) instead of optional (facultatif). */
  requireTaille?: boolean;
}

/** Returns true if all required fields are filled. Use to gate the submit button. */
export function isOrgFormFieldsValid(
  values: OrgFormFieldsValues,
  options: { requireTaille?: boolean } = {},
): boolean {
  if (!values.name.trim()) return false;
  if (options.requireTaille && !values.taille) return false;
  return true;
}

export function OrgFormFields({
  values,
  onChange,
  token,
  hideCcn = false,
  requireTaille = false,
}: OrgFormFieldsProps) {
  const set = <K extends keyof OrgFormFieldsValues>(
    key: K,
    value: OrgFormFieldsValues[K],
  ) => onChange({ ...values, [key]: value });

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor="org-name">
          Nom de l&apos;entreprise{" "}
          <span className="text-destructive">*</span>
        </Label>
        <Input
          id="org-name"
          value={values.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="Ex : Waibly SAS"
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="forme-juridique">
          Forme juridique{" "}
          <span className="text-muted-foreground text-xs font-normal">(facultatif)</span>
        </Label>
        <Select
          value={values.formeJuridique}
          onValueChange={(v) => set("formeJuridique", v)}
        >
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
        <Label htmlFor="taille">
          Effectif{" "}
          {requireTaille ? (
            <span className="text-destructive">*</span>
          ) : (
            <span className="text-muted-foreground text-xs font-normal">(facultatif)</span>
          )}
        </Label>
        <Select
          value={values.taille || TAILLE_NON_PRECISE}
          onValueChange={(v) =>
            set("taille", v === TAILLE_NON_PRECISE ? "" : v)
          }
        >
          <SelectTrigger id="taille">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {/* Choix neutre par défaut : effectif non transmis au moteur, les
                réponses ne raisonnent pas par seuil (11, 50…). Valeur stockée
                vide ("") — Radix interdit une SelectItem à valeur vide, d'où la
                sentinelle mappée sur "". */}
            <SelectItem value={TAILLE_NON_PRECISE}>Non précisé</SelectItem>
            {TAILLE_OPTIONS.map((t) => (
              <SelectItem key={t} value={t}>
                {t} salariés
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="secteur">
          Secteur d&apos;activité / code APE{" "}
          <span className="text-muted-foreground text-xs font-normal">(facultatif)</span>
        </Label>
        <Input
          id="secteur"
          value={values.secteurActivite}
          onChange={(e) => set("secteurActivite", e.target.value)}
          placeholder="Ex : 62.01Z — Programmation informatique"
        />
        <p className="text-xs text-muted-foreground">
          Vous le trouverez sur votre Kbis ou pourrez l&apos;ajouter plus tard.
        </p>
      </div>

      {!hideCcn && (
        <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
          <div className="space-y-1.5">
            <Label>
              Convention(s) collective(s){" "}
              <span className="text-muted-foreground text-xs font-normal">(facultatif)</span>
            </Label>
            <CcnSelector
              token={token}
              selected={values.selectedCcn}
              onChange={(ccn) => set("selectedCcn", ccn)}
              disabled={values.notSubjectToCcn}
            />
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer pt-1">
            <Checkbox
              id="not-subject-to-ccn"
              checked={values.notSubjectToCcn}
              onCheckedChange={(checked) => {
                const isChecked = checked === true;
                onChange({
                  ...values,
                  notSubjectToCcn: isChecked,
                  // Si on coche, on vide la sélection CCN.
                  selectedCcn: isChecked ? [] : values.selectedCcn,
                });
              }}
              className="mt-0.5"
            />
            <span className="text-sm leading-snug">
              Mon organisation n&apos;est pas soumise à une convention collective
            </span>
          </label>
        </div>
      )}
    </>
  );
}

export function emptyOrgFormFields(): OrgFormFieldsValues {
  return {
    name: "",
    formeJuridique: "",
    taille: "",
    secteurActivite: "",
    selectedCcn: [],
    notSubjectToCcn: false,
  };
}
