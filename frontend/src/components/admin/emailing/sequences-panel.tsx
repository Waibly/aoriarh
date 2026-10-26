"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminLoadError } from "@/components/admin/page-header";
import { useSession } from "next-auth/react";
import {
  Loader2,
  Plus,
  Pencil,
  Trash2,
  ArrowDown,
  ArrowUp,
  GitBranch,
} from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface StepBranch {
  id: string;
  condition: string;
  template_id: string;
  template_name: string | null;
  template_subject: string | null;
}

interface SequenceStep {
  id: string;
  template_id: string | null;
  position: number;
  delay_days: number;
  template_name: string | null;
  template_subject: string | null;
  branches: StepBranch[];
}

interface EmailSequence {
  id: string;
  name: string;
  status: string;
  steps: SequenceStep[];
  created_at: string;
  updated_at: string;
}

interface EmailTemplate {
  id: string;
  name: string;
  subject: string;
}

interface BranchForm {
  condition: string;
  template_id: string;
}

interface StepForm {
  template_id: string | null;
  delay_days: number;
  branches: BranchForm[];
}

const CONDITION_LABELS: Record<string, string> = {
  opened_and_clicked: "Ouvert + cliqué",
  opened_not_clicked: "Ouvert, pas cliqué",
  not_opened: "Pas ouvert",
};

const ALL_CONDITIONS = [
  "opened_and_clicked",
  "opened_not_clicked",
  "not_opened",
];

const STATUS_BADGE: Record<
  string,
  { label: string; variant: "default" | "secondary" | "outline" }
> = {
  draft: { label: "Brouillon", variant: "outline" },
  active: { label: "Active", variant: "default" },
  paused: { label: "En pause", variant: "secondary" },
  completed: { label: "Terminée", variant: "secondary" },
};

export default function SequencesPanel() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [sequences, setSequences] = useState<EmailSequence[]>([]);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formSteps, setFormSteps] = useState<StepForm[]>([]);
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<EmailSequence | null>(null);

  const fetchData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(false);
    try {
      const [seqs, tpls] = await Promise.all([
        apiFetch<EmailSequence[]>("/admin/emailing/sequences", { token }),
        apiFetch<EmailTemplate[]>("/admin/emailing/templates", { token }),
      ]);
      setSequences(seqs);
      setTemplates(tpls);
    } catch {
      setError(true);
      toast.error("Erreur lors du chargement");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function openCreate() {
    setEditId(null);
    setFormName("");
    setFormSteps([]);
    setEditOpen(true);
  }

  function openEdit(seq: EmailSequence) {
    setEditId(seq.id);
    setFormName(seq.name);
    setFormSteps(
      seq.steps.map((s) => ({
        template_id: s.template_id,
        delay_days: s.delay_days,
        branches: s.branches.map((b) => ({
          condition: b.condition,
          template_id: b.template_id,
        })),
      }))
    );
    setEditOpen(true);
  }

  function addStep() {
    if (templates.length === 0) {
      toast.error("Créez d’abord un modèle d’email");
      return;
    }
    const isFirst = formSteps.length === 0;
    setFormSteps([
      ...formSteps,
      {
        template_id: isFirst ? templates[0].id : null,
        delay_days: isFirst ? 0 : 5,
        branches: isFirst
          ? []
          : ALL_CONDITIONS.map((c) => ({
              condition: c,
              template_id: templates[0].id,
            })),
      },
    ]);
  }

  function removeStep(index: number) {
    setFormSteps(formSteps.filter((_, i) => i !== index));
  }

  function moveStep(index: number, direction: "up" | "down") {
    const newSteps = [...formSteps];
    const target = direction === "up" ? index - 1 : index + 1;
    if (target < 0 || target >= newSteps.length) return;
    [newSteps[index], newSteps[target]] = [newSteps[target], newSteps[index]];
    setFormSteps(newSteps);
  }

  function updateStep(
    index: number,
    field: string,
    value: string | number | null
  ) {
    const newSteps = [...formSteps];
    newSteps[index] = { ...newSteps[index], [field]: value };
    setFormSteps(newSteps);
  }

  function updateBranch(
    stepIndex: number,
    branchIndex: number,
    field: string,
    value: string
  ) {
    const newSteps = [...formSteps];
    const newBranches = [...newSteps[stepIndex].branches];
    newBranches[branchIndex] = { ...newBranches[branchIndex], [field]: value };
    newSteps[stepIndex] = { ...newSteps[stepIndex], branches: newBranches };
    setFormSteps(newSteps);
  }

  async function handleSave() {
    if (!token || !formName.trim()) return;
    setSaving(true);
    try {
      const steps = formSteps.map((s, i) => ({
        template_id: s.template_id,
        position: i + 1,
        delay_days: s.delay_days,
        branches: s.branches.map((b) => ({
          condition: b.condition,
          template_id: b.template_id,
        })),
      }));

      const body = JSON.stringify({ name: formName.trim(), steps });

      if (editId) {
        await apiFetch(`/admin/emailing/sequences/${editId}`, {
          method: "PUT",
          token,
          body,
        });
        toast.success("Séquence modifiée");
      } else {
        await apiFetch("/admin/emailing/sequences", {
          method: "POST",
          token,
          body,
        });
        toast.success("Séquence créée");
      }

      setEditOpen(false);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!token || !deleteTarget) return;
    try {
      await apiFetch(`/admin/emailing/sequences/${deleteTarget.id}`, {
        method: "DELETE",
        token,
      });
      toast.success("Séquence supprimée");
      setDeleteTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Séquences</h2>
          <p className="text-muted-foreground text-sm">
            Définissez l’ordre des emails, les délais et les relances selon les
            réactions de vos contacts.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Nouvelle séquence
        </Button>
      </div>

      {error && (
        <AdminLoadError
          message="Impossible de charger les séquences et leurs modèles."
          onRetry={fetchData}
        />
      )}
      <Card>
        <CardContent className="p-0 sm:p-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Étapes</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center">
                    <Loader2 className="text-muted-foreground mx-auto h-6 w-6 animate-spin" />
                  </TableCell>
                </TableRow>
              ) : error ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground py-8 text-center"
                  >
                    Données indisponibles.
                  </TableCell>
                </TableRow>
              ) : sequences.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground py-8 text-center"
                  >
                    Aucune séquence créée
                  </TableCell>
                </TableRow>
              ) : (
                sequences.map((seq) => {
                  const badge = STATUS_BADGE[seq.status] ?? {
                    label: seq.status,
                    variant: "outline" as const,
                  };
                  return (
                    <TableRow key={seq.id}>
                      <TableCell className="font-medium">{seq.name}</TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          {seq.steps.map((step) => (
                            <div key={step.id}>
                              <div className="text-muted-foreground text-xs">
                                Jour {step.delay_days} —{" "}
                                {step.template_name ?? "Branchement"}
                              </div>
                              {step.branches.length > 0 && (
                                <div className="space-y-0.5 pl-4">
                                  {step.branches.map((b) => (
                                    <div
                                      key={b.id}
                                      className="text-muted-foreground flex items-center gap-1 text-xs"
                                    >
                                      <GitBranch className="h-3 w-3" />
                                      {CONDITION_LABELS[b.condition] ??
                                        b.condition}{" "}
                                      → {b.template_name}
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                          {seq.steps.length === 0 && (
                            <span className="text-muted-foreground text-xs">
                              Aucune étape
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => openEdit(seq)}
                            title="Modifier"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          {seq.status !== "active" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setDeleteTarget(seq)}
                              title="Supprimer"
                            >
                              <Trash2 className="text-destructive h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Dialog : Créer / Modifier */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              {editId ? "Modifier la séquence" : "Nouvelle séquence"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Nom</Label>
              <Input
                placeholder="Ex : Prospection CSE"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Label>Étapes</Label>
                <Button variant="outline" size="sm" onClick={addStep}>
                  <Plus className="mr-1 h-3 w-3" />
                  Ajouter
                </Button>
              </div>
              {formSteps.length === 0 && (
                <p className="text-muted-foreground py-4 text-center text-sm">
                  Aucune étape. Cliquez sur &quot;Ajouter&quot; pour commencer.
                </p>
              )}
              {formSteps.map((step, index) => {
                const isFirst = index === 0;
                const hasBranches = step.branches.length > 0;

                return (
                  <Card
                    key={index}
                    className={hasBranches ? "border-primary/30" : ""}
                  >
                    <CardContent className="space-y-3 p-3">
                      <div className="flex items-center gap-3">
                        <span className="text-muted-foreground w-6 text-sm font-medium">
                          {index + 1}.
                        </span>
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            <div className="flex-1 space-y-1">
                              <Label className="text-xs">Délai (jours)</Label>
                              <Input
                                type="number"
                                min="0"
                                className="h-8 text-xs"
                                value={step.delay_days}
                                onChange={(e) =>
                                  updateStep(
                                    index,
                                    "delay_days",
                                    parseInt(e.target.value) || 0
                                  )
                                }
                              />
                            </div>
                            {isFirst && (
                              <div className="flex-[2] space-y-1">
                                <Label className="text-xs">Modèle</Label>
                                <Select
                                  value={step.template_id ?? ""}
                                  onValueChange={(v) =>
                                    updateStep(index, "template_id", v)
                                  }
                                >
                                  <SelectTrigger className="h-8 text-xs">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {templates.map((t) => (
                                      <SelectItem key={t.id} value={t.id}>
                                        {t.name}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            )}
                            {!isFirst && !hasBranches && (
                              <div className="flex-[2] space-y-1">
                                <Label className="text-xs">
                                  Modèle (même pour tous)
                                </Label>
                                <Select
                                  value={step.template_id ?? ""}
                                  onValueChange={(v) =>
                                    updateStep(index, "template_id", v)
                                  }
                                >
                                  <SelectTrigger className="h-8 text-xs">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {templates.map((t) => (
                                      <SelectItem key={t.id} value={t.id}>
                                        {t.name}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex flex-col gap-0.5">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            onClick={() => moveStep(index, "up")}
                            disabled={index === 0}
                          >
                            <ArrowUp className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            onClick={() => moveStep(index, "down")}
                            disabled={index === formSteps.length - 1}
                          >
                            <ArrowDown className="h-3 w-3" />
                          </Button>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6"
                          onClick={() => removeStep(index)}
                        >
                          <Trash2 className="text-destructive h-3 w-3" />
                        </Button>
                      </div>

                      {/* Branches */}
                      {hasBranches && (
                        <div className="space-y-2 pl-8">
                          <div className="text-muted-foreground flex items-center gap-2 text-xs">
                            <GitBranch className="h-3.5 w-3.5" />
                            Selon le résultat de l&apos;étape précédente :
                          </div>
                          {step.branches.map((branch, bi) => (
                            <div
                              key={bi}
                              className="border-primary/20 flex items-center gap-2 border-l-2 pl-2"
                            >
                              <Badge
                                variant="outline"
                                className="shrink-0 text-xs"
                              >
                                {CONDITION_LABELS[branch.condition]}
                              </Badge>
                              <span className="text-muted-foreground text-xs">
                                →
                              </span>
                              <Select
                                value={branch.template_id}
                                onValueChange={(v) =>
                                  updateBranch(index, bi, "template_id", v)
                                }
                              >
                                <SelectTrigger className="h-7 flex-1 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {templates.map((t) => (
                                    <SelectItem key={t.id} value={t.id}>
                                      {t.name}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </div>
                          ))}
                        </div>
                      )}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Annuler
            </Button>
            <Button onClick={handleSave} disabled={saving || !formName.trim()}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editId ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Supprimer */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette séquence ?</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground text-sm">
            La séquence &laquo;&nbsp;{deleteTarget?.name}&nbsp;&raquo; sera
            supprimée définitivement.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
