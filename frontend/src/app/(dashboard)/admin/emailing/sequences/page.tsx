"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Pencil, Trash2, ArrowDown, ArrowUp } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
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

interface SequenceStep {
  id: string;
  template_id: string;
  position: number;
  delay_days: number;
  template_name: string | null;
  template_subject: string | null;
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

interface StepForm {
  template_id: string;
  delay_days: number;
}

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
  draft: { label: "Brouillon", variant: "outline" },
  active: { label: "Active", variant: "default" },
  paused: { label: "En pause", variant: "secondary" },
  completed: { label: "Terminée", variant: "secondary" },
};

export default function AdminEmailSequencesPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [sequences, setSequences] = useState<EmailSequence[]>([]);
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formSteps, setFormSteps] = useState<StepForm[]>([]);
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<EmailSequence | null>(null);

  const fetchData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [seqs, tpls] = await Promise.all([
        apiFetch<EmailSequence[]>("/admin/emailing/sequences", { token }),
        apiFetch<EmailTemplate[]>("/admin/emailing/templates", { token }),
      ]);
      setSequences(seqs);
      setTemplates(tpls);
    } catch {
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
    setFormSteps(seq.steps.map((s) => ({
      template_id: s.template_id,
      delay_days: s.delay_days,
    })));
    setEditOpen(true);
  }

  function addStep() {
    if (templates.length === 0) {
      toast.error("Créez d'abord un template");
      return;
    }
    setFormSteps([...formSteps, { template_id: templates[0].id, delay_days: formSteps.length === 0 ? 0 : 3 }]);
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

  function updateStep(index: number, field: keyof StepForm, value: string | number) {
    const newSteps = [...formSteps];
    newSteps[index] = { ...newSteps[index], [field]: value };
    setFormSteps(newSteps);
  }

  async function handleSave() {
    if (!token || !formName.trim()) return;
    setSaving(true);
    try {
      const body = JSON.stringify({
        name: formName.trim(),
        steps: formSteps.map((s, i) => ({
          template_id: s.template_id,
          position: i + 1,
          delay_days: s.delay_days,
        })),
      });

      if (editId) {
        await apiFetch(`/admin/emailing/sequences/${editId}`, { method: "PUT", token, body });
        toast.success("Séquence modifiée");
      } else {
        await apiFetch("/admin/emailing/sequences", { method: "POST", token, body });
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
      await apiFetch(`/admin/emailing/sequences/${deleteTarget.id}`, { method: "DELETE", token });
      toast.success("Séquence supprimée");
      setDeleteTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  const getTemplateName = (id: string) => templates.find((t) => t.id === id)?.name ?? "—";

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Séquences</h1>
          <p className="text-sm text-muted-foreground">
            Suites d&apos;emails envoyés automatiquement dans le temps
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Nouvelle séquence
        </Button>
      </div>

      <Card>
        <CardContent className="p-4">
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
                  <TableCell colSpan={4} className="text-center py-8">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : sequences.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                    Aucune séquence créée
                  </TableCell>
                </TableRow>
              ) : (
                sequences.map((seq) => {
                  const badge = STATUS_BADGE[seq.status] ?? { label: seq.status, variant: "outline" as const };
                  return (
                    <TableRow key={seq.id}>
                      <TableCell className="font-medium">{seq.name}</TableCell>
                      <TableCell>
                        <div className="space-y-0.5">
                          {seq.steps.map((step) => (
                            <div key={step.id} className="text-xs text-muted-foreground">
                              Jour {step.delay_days} — {step.template_name ?? "—"}
                            </div>
                          ))}
                          {seq.steps.length === 0 && <span className="text-xs text-muted-foreground">Aucune étape</span>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="icon" onClick={() => openEdit(seq)} title="Modifier">
                            <Pencil className="h-4 w-4" />
                          </Button>
                          {seq.status !== "active" && (
                            <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(seq)} title="Supprimer">
                              <Trash2 className="h-4 w-4 text-destructive" />
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
        <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editId ? "Modifier la séquence" : "Nouvelle séquence"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Nom</Label>
              <Input
                placeholder="Ex : Prospection RH"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>Étapes</Label>
                <Button variant="outline" size="sm" onClick={addStep}>
                  <Plus className="mr-1 h-3 w-3" />
                  Ajouter
                </Button>
              </div>
              {formSteps.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Aucune étape. Cliquez sur &quot;Ajouter&quot; pour commencer.
                </p>
              )}
              {formSteps.map((step, index) => (
                <Card key={index}>
                  <CardContent className="p-3">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-medium text-muted-foreground w-6">
                        {index + 1}.
                      </span>
                      <div className="flex-1 grid grid-cols-2 gap-3">
                        <div className="space-y-1">
                          <Label className="text-xs">Template</Label>
                          <Select
                            value={step.template_id}
                            onValueChange={(v) => updateStep(index, "template_id", v)}
                          >
                            <SelectTrigger className="h-8 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {templates.map((t) => (
                                <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Délai (jours après lancement)</Label>
                          <Input
                            type="number"
                            min="0"
                            className="h-8 text-xs"
                            value={step.delay_days}
                            onChange={(e) => updateStep(index, "delay_days", parseInt(e.target.value) || 0)}
                          />
                        </div>
                      </div>
                      <div className="flex flex-col gap-0.5">
                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => moveStep(index, "up")} disabled={index === 0}>
                          <ArrowUp className="h-3 w-3" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => moveStep(index, "down")} disabled={index === formSteps.length - 1}>
                          <ArrowDown className="h-3 w-3" />
                        </Button>
                      </div>
                      <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeStep(index)}>
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>Annuler</Button>
            <Button onClick={handleSave} disabled={saving || !formName.trim()}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {editId ? "Enregistrer" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Supprimer */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette séquence ?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            La séquence &laquo;&nbsp;{deleteTarget?.name}&nbsp;&raquo; sera supprimée définitivement.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Annuler</Button>
            <Button variant="destructive" onClick={handleDelete}>Supprimer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
