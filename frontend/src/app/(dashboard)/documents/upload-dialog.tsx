"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { toast } from "sonner";
import { authFetch } from "@/lib/api";
import { SOURCE_TYPE_OPTIONS, NORME_POIDS } from "@/types/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";

const NIVEAU_LABELS: Record<number, string> = {
  1: "Constitution",
  2: "Normes internationales",
  3: "Lois & Ordonnances",
  4: "Jurisprudence",
  5: "Réglementaire",
  6: "Conventions collectives",
  7: "Usages & Engagements",
  8: "Règlement intérieur",
  9: "Contrat de travail",
  10: "Divers",
};

const JURISPRUDENCE_SOURCE_TYPES = new Set([
  "arret_cour_cassation",
  "arret_conseil_etat",
  "decision_conseil_constitutionnel",
]);

const JURIDICTION_OPTIONS = [
  "Cour de cassation",
  "Conseil d'État",
  "Conseil constitutionnel",
] as const;

const CHAMBRE_OPTIONS = [
  "Chambre sociale",
  "Chambre civile 1",
  "Chambre civile 2",
  "Chambre civile 3",
  "Chambre commerciale",
  "Chambre criminelle",
  "Assemblée plénière",
  "Chambre mixte",
] as const;

const FORMATION_OPTIONS = [
  "Formation plénière de chambre",
  "Formation restreinte",
  "Section",
] as const;

const SOLUTION_OPTIONS = [
  "Cassation",
  "Cassation partielle",
  "Rejet",
  "QPC",
  "Non-lieu à statuer",
] as const;

const PUBLICATION_OPTIONS = [
  "Publié au Bulletin",
  "Inédit",
  "Mentionné aux tables",
] as const;

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  token?: string;
  onUploaded: () => void;
  initialSourceType?: string;
}

export function UploadDialog({
  open,
  onOpenChange,
  orgId,
  token,
  onUploaded,
  initialSourceType,
}: UploadDialogProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [sourceType, setSourceType] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Jurisprudence metadata
  const [juridiction, setJuridiction] = useState("");
  const [chambre, setChambre] = useState("");
  const [formation, setFormation] = useState("");
  const [numeroPourvoi, setNumeroPourvoi] = useState("");
  const [dateDecision, setDateDecision] = useState("");
  const [solution, setSolution] = useState("");
  const [publication, setPublication] = useState("");

  const isJurisprudence = JURISPRUDENCE_SOURCE_TYPES.has(sourceType);
  const isBatch = files.length > 1;

  const selectedOption = SOURCE_TYPE_OPTIONS.find((s) => s.value === sourceType);
  const niveau = selectedOption?.niveau;
  const poids = niveau ? NORME_POIDS[niveau] : null;

  const [typeSearchOpen, setTypeSearchOpen] = useState(false);
  const [typeSearch, setTypeSearch] = useState("");

  useEffect(() => {
    if (open) {
      setFiles([]);
      setSourceType(initialSourceType ?? "");
      setError(null);
      setJuridiction("");
      setChambre("");
      setFormation("");
      setNumeroPourvoi("");
      setDateDecision("");
      setSolution("");
      setPublication("");
      setTypeSearch("");
      setTypeSearchOpen(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [open, initialSourceType]);

  // Listen for dropped files from drag & drop zone
  useEffect(() => {
    const handleOne = (e: Event) => {
      const droppedFile = (e as CustomEvent<File>).detail;
      if (droppedFile) setFiles([droppedFile]);
    };
    const handleMany = (e: Event) => {
      const droppedFiles = (e as CustomEvent<File[]>).detail;
      if (droppedFiles?.length) setFiles(droppedFiles);
    };
    window.addEventListener("dropped-file", handleOne);
    window.addEventListener("dropped-files", handleMany);
    return () => {
      window.removeEventListener("dropped-file", handleOne);
      window.removeEventListener("dropped-files", handleMany);
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (files.length === 0 || !sourceType) return;

    setSubmitting(true);
    setError(null);

    try {
      if (isBatch) {
        const formData = new FormData();
        for (const f of files) formData.append("files", f);
        formData.append("source_type", sourceType);

        const res = await authFetch(`/documents/${orgId}/batch`, {
          method: "POST",
          body: formData,
          token: token ?? undefined,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail ?? "Erreur lors de l'upload");
        }

        const data = await res.json();
        type BatchResult = {
          filename: string;
          success: boolean;
          error?: string | null;
        };
        const failedResults: BatchResult[] = (data.results ?? []).filter(
          (r: BatchResult) => !r.success,
        );

        // Group failures by exact error message to build a precise description
        const reasonCounts = new Map<string, number>();
        for (const r of failedResults) {
          const reason = r.error?.trim() || "Erreur inconnue";
          reasonCounts.set(reason, (reasonCounts.get(reason) ?? 0) + 1);
        }
        const description = Array.from(reasonCounts.entries())
          .map(([reason, count]) =>
            count > 1 ? `${count} fichiers : ${reason}` : reason,
          )
          .join("\n");

        if (data.failed > 0 && data.succeeded === 0) {
          toast.warning(
            `${data.failed} document${data.failed > 1 ? "s" : ""} non ajouté${data.failed > 1 ? "s" : ""}`,
            { description, duration: 7000 },
          );
        } else if (data.failed > 0) {
          toast.success(
            `${data.succeeded} document${data.succeeded > 1 ? "s" : ""} ajouté${data.succeeded > 1 ? "s" : ""}`,
            {
              description: `${data.failed} ignoré${data.failed > 1 ? "s" : ""} :\n${description}`,
              duration: 7000,
            },
          );
        } else {
          toast.success(
            `${data.succeeded} document${data.succeeded > 1 ? "s" : ""} ajouté${data.succeeded > 1 ? "s" : ""}`,
          );
        }
        // Batch upload changed the docs counter — ping listeners so
        // the sidebar and /billing usage card refresh without a reload.
        if (typeof window !== "undefined" && data.succeeded > 0) {
          window.dispatchEvent(new Event("quota-updated"));
        }
      } else {
        const formData = new FormData();
        formData.append("file", files[0]);
        formData.append("source_type", sourceType);
        if (isJurisprudence) {
          if (juridiction) formData.append("juridiction", juridiction);
          if (chambre) formData.append("chambre", chambre);
          if (formation) formData.append("formation", formation);
          if (numeroPourvoi) formData.append("numero_pourvoi", numeroPourvoi);
          if (dateDecision) formData.append("date_decision", dateDecision);
          if (solution) formData.append("solution", solution);
          if (publication) formData.append("publication", publication);
        }

        const res = await authFetch(`/documents/${orgId}/`, {
          method: "POST",
          body: formData,
          token: token ?? undefined,
        });

        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail ?? "Erreur lors de l'upload");
        }

        toast.success("Document ajouté");
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("quota-updated"));
        }
      }

      onOpenChange(false);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de l'upload");
    } finally {
      setSubmitting(false);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // Filter to org-relevant types (niveaux 6+) and group by niveau
  const orgTypeOptions = SOURCE_TYPE_OPTIONS.filter((o) => o.niveau >= 6);
  const grouped = new Map<number, typeof SOURCE_TYPE_OPTIONS>();
  for (const opt of orgTypeOptions) {
    const group = grouped.get(opt.niveau) ?? [];
    group.push(opt);
    grouped.set(opt.niveau, group);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Ajouter des documents</DialogTitle>
          <DialogDescription>
            Sélectionnez un ou plusieurs fichiers du même type. Formats acceptés :
            PDF, Word (.docx), Texte (.txt)
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="doc-file">
              Fichier{files.length > 1 ? "s" : ""} *
              {files.length > 0 && (
                <span className="text-muted-foreground ml-1">
                  ({files.length} sélectionné{files.length > 1 ? "s" : ""})
                </span>
              )}
            </Label>
            <input
              ref={fileRef}
              id="doc-file"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-4 file:py-2 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
              required={files.length === 0}
            />
            {files.length > 1 && (
              <div className="max-h-32 overflow-y-auto rounded-md border p-2 space-y-1">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="truncate mr-2">{f.name}</span>
                    <button
                      type="button"
                      onClick={() => removeFile(i)}
                      className="text-destructive hover:underline shrink-0"
                    >
                      Retirer
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label>Type de document *</Label>
            <Popover open={typeSearchOpen} onOpenChange={setTypeSearchOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  role="combobox"
                  aria-expanded={typeSearchOpen}
                  className="w-full justify-between font-normal"
                >
                  <span className={cn(!sourceType && "text-muted-foreground")}>
                    {sourceType
                      ? orgTypeOptions.find((o) => o.value === sourceType)?.label ?? sourceType
                      : "Sélectionner le type..."}
                  </span>
                  <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                className="w-[--radix-popover-trigger-width] p-0"
                align="start"
              >
                <Command shouldFilter={false}>
                  <CommandInput
                    placeholder="Rechercher un type..."
                    value={typeSearch}
                    onValueChange={setTypeSearch}
                  />
                  <CommandList className="max-h-none">
                    <CommandEmpty>Aucun type trouvé.</CommandEmpty>
                    {Array.from(grouped.entries()).map(([niv, options]) => {
                      const filtered = typeSearch
                        ? options.filter((o) =>
                            o.label.toLowerCase().includes(typeSearch.toLowerCase()),
                          )
                        : options;
                      if (filtered.length === 0) return null;
                      return (
                        <CommandGroup key={niv} heading={NIVEAU_LABELS[niv]}>
                          {filtered.map((opt) => (
                            <CommandItem
                              key={opt.value}
                              onSelect={() => {
                                setSourceType(opt.value);
                                setTypeSearchOpen(false);
                                setTypeSearch("");
                              }}
                            >
                              <Check
                                className={cn(
                                  "mr-2 h-4 w-4",
                                  sourceType === opt.value ? "opacity-100" : "opacity-0",
                                )}
                              />
                              {opt.label}
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      );
                    })}
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          {niveau && (
            <div className="flex gap-6 rounded-md border p-3 text-sm">
              <div>
                <span className="text-muted-foreground">Niveau : </span>
                <span className="font-medium">
                  {niveau} — {NIVEAU_LABELS[niveau]}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Poids : </span>
                <span className="font-medium">{poids}</span>
              </div>
            </div>
          )}

          {isJurisprudence && !isBatch && (
            <div className="space-y-3 rounded-md border border-border bg-muted/50 p-4">
              <p className="text-sm font-medium">Métadonnées jurisprudence</p>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="juridiction" className="text-xs">Juridiction</Label>
                  <Select value={juridiction} onValueChange={setJuridiction}>
                    <SelectTrigger id="juridiction">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {JURIDICTION_OPTIONS.map((j) => (
                        <SelectItem key={j} value={j}>{j}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="chambre" className="text-xs">Chambre</Label>
                  <Select value={chambre} onValueChange={setChambre}>
                    <SelectTrigger id="chambre">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {CHAMBRE_OPTIONS.map((c) => (
                        <SelectItem key={c} value={c}>{c}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="formation" className="text-xs">Formation</Label>
                  <Select value={formation} onValueChange={setFormation}>
                    <SelectTrigger id="formation">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {FORMATION_OPTIONS.map((f) => (
                        <SelectItem key={f} value={f}>{f}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="numero-pourvoi" className="text-xs">N° de pourvoi</Label>
                  <Input
                    id="numero-pourvoi"
                    placeholder="ex: 21-14.490"
                    value={numeroPourvoi}
                    onChange={(e) => setNumeroPourvoi(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="date-decision" className="text-xs">Date de décision</Label>
                  <Input
                    id="date-decision"
                    type="date"
                    value={dateDecision}
                    onChange={(e) => setDateDecision(e.target.value)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="solution" className="text-xs">Solution</Label>
                  <Select value={solution} onValueChange={setSolution}>
                    <SelectTrigger id="solution">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {SOLUTION_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>{s}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="col-span-2 space-y-1">
                  <Label htmlFor="publication" className="text-xs">Publication</Label>
                  <Select value={publication} onValueChange={setPublication}>
                    <SelectTrigger id="publication">
                      <SelectValue placeholder="Sélectionner..." />
                    </SelectTrigger>
                    <SelectContent>
                      {PUBLICATION_OPTIONS.map((p) => (
                        <SelectItem key={p} value={p}>{p}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          {isBatch && isJurisprudence && (
            <p className="text-xs text-muted-foreground">
              Les métadonnées de jurisprudence ne sont pas disponibles en upload par lot.
            </p>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || files.length === 0 || !sourceType}
            >
              {submitting
                ? "Upload en cours..."
                : files.length > 1
                  ? `Ajouter ${files.length} documents`
                  : "Ajouter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
