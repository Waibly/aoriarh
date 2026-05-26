"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Play, Pause, RotateCcw, Trash2, BarChart3 } from "lucide-react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface EmailSequence {
  id: string;
  name: string;
  status: string;
}

interface BrevoList {
  id: number;
  name: string;
  total_subscribers: number;
}

interface EmailCampaign {
  id: string;
  name: string;
  sequence_id: string;
  sequence_name: string | null;
  brevo_list_ids: number[];
  status: string;
  scheduled_at: string | null;
  current_step: number;
  recipient_count: number;
  created_at: string;
}

interface BranchStats {
  condition: string;
  template_name: string | null;
  sent: number;
  opened: number;
  clicked: number;
  bounced: number;
  unsubscribed: number;
}

interface StepStats {
  step_position: number;
  template_name: string | null;
  delay_days: number;
  sent: number;
  opened: number;
  clicked: number;
  bounced: number;
  unsubscribed: number;
  branches: BranchStats[];
}

const CONDITION_LABELS: Record<string, string> = {
  opened_and_clicked: "Ouvert + cliqué",
  opened_not_clicked: "Ouvert, pas cliqué",
  not_opened: "Pas ouvert",
};

interface CampaignStats {
  campaign_id: string;
  campaign_name: string;
  status: string;
  total_recipients: number;
  steps: StepStats[];
}

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "outline" | "destructive" }> = {
  draft: { label: "Brouillon", variant: "outline" },
  running: { label: "En cours", variant: "default" },
  paused: { label: "En pause", variant: "secondary" },
  completed: { label: "Terminée", variant: "secondary" },
};

export default function AdminEmailCampaignsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [sequences, setSequences] = useState<EmailSequence[]>([]);
  const [brevoLists, setBrevoLists] = useState<BrevoList[]>([]);
  const [loading, setLoading] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [formName, setFormName] = useState("");
  const [formSequenceId, setFormSequenceId] = useState("");
  const [formListIds, setFormListIds] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);

  const [statsOpen, setStatsOpen] = useState(false);
  const [stats, setStats] = useState<CampaignStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<EmailCampaign | null>(null);
  const [launchTarget, setLaunchTarget] = useState<EmailCampaign | null>(null);

  const fetchData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [camps, seqs, lists] = await Promise.all([
        apiFetch<EmailCampaign[]>("/admin/emailing/campaigns", { token }),
        apiFetch<EmailSequence[]>("/admin/emailing/sequences", { token }),
        apiFetch<BrevoList[]>("/admin/emailing/lists", { token }),
      ]);
      setCampaigns(camps);
      setSequences(seqs);
      setBrevoLists(lists);
    } catch {
      toast.error("Erreur lors du chargement");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function toggleList(listId: number) {
    setFormListIds((prev) =>
      prev.includes(listId) ? prev.filter((id) => id !== listId) : [...prev, listId]
    );
  }

  async function handleCreate() {
    if (!token || !formName.trim() || !formSequenceId || formListIds.length === 0) return;
    setSaving(true);
    try {
      await apiFetch("/admin/emailing/campaigns", {
        method: "POST",
        token,
        body: JSON.stringify({
          name: formName.trim(),
          sequence_id: formSequenceId,
          brevo_list_ids: formListIds,
        }),
      });
      toast.success("Campagne créée");
      setCreateOpen(false);
      setFormName("");
      setFormSequenceId("");
      setFormListIds([]);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSaving(false);
    }
  }

  async function handleLaunch() {
    if (!token || !launchTarget) return;
    try {
      await apiFetch(`/admin/emailing/campaigns/${launchTarget.id}/launch`, {
        method: "POST", token,
      });
      toast.success("Campagne lancée");
      setLaunchTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function handlePause(id: string) {
    if (!token) return;
    try {
      await apiFetch(`/admin/emailing/campaigns/${id}/pause`, { method: "POST", token });
      toast.success("Campagne mise en pause");
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function handleResume(id: string) {
    if (!token) return;
    try {
      await apiFetch(`/admin/emailing/campaigns/${id}/resume`, { method: "POST", token });
      toast.success("Campagne relancée");
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function handleDelete() {
    if (!token || !deleteTarget) return;
    try {
      await apiFetch(`/admin/emailing/campaigns/${deleteTarget.id}`, { method: "DELETE", token });
      toast.success("Campagne supprimée");
      setDeleteTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function openStats(campaign: EmailCampaign) {
    if (!token) return;
    setStatsOpen(true);
    setLoadingStats(true);
    try {
      const data = await apiFetch<CampaignStats>(
        `/admin/emailing/campaigns/${campaign.id}/stats`,
        { token },
      );
      setStats(data);
    } catch {
      toast.error("Erreur lors du chargement des stats");
    } finally {
      setLoadingStats(false);
    }
  }

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("fr-FR", {
      day: "numeric", month: "short", year: "numeric",
    });

  const listName = (id: number) => brevoLists.find((l) => l.id === id)?.name ?? `#${id}`;

  const pct = (n: number, total: number) =>
    total > 0 ? `${Math.round((n / total) * 100)}%` : "—";

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Campagnes</h1>
          <p className="text-sm text-muted-foreground">
            Lancer une séquence vers une ou plusieurs listes de contacts
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Nouvelle campagne
        </Button>
      </div>

      <Card>
        <CardContent className="p-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Séquence</TableHead>
                <TableHead>Listes</TableHead>
                <TableHead>Contacts</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Lancée le</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : campaigns.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    Aucune campagne créée
                  </TableCell>
                </TableRow>
              ) : (
                campaigns.map((c) => {
                  const badge = STATUS_BADGE[c.status] ?? { label: c.status, variant: "outline" as const };
                  return (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell className="text-muted-foreground">{c.sequence_name ?? "—"}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {c.brevo_list_ids.map((id) => (
                            <Badge key={id} variant="outline" className="text-xs">{listName(id)}</Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>{c.recipient_count}</TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {c.scheduled_at ? fmt(c.scheduled_at) : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {c.status === "draft" && (
                            <Button variant="ghost" size="icon" onClick={() => setLaunchTarget(c)} title="Lancer">
                              <Play className="h-4 w-4 text-green-600" />
                            </Button>
                          )}
                          {c.status === "running" && (
                            <Button variant="ghost" size="icon" onClick={() => handlePause(c.id)} title="Pause">
                              <Pause className="h-4 w-4" />
                            </Button>
                          )}
                          {c.status === "paused" && (
                            <>
                              <Button variant="ghost" size="icon" onClick={() => handleResume(c.id)} title="Reprendre">
                                <RotateCcw className="h-4 w-4" />
                              </Button>
                              <Button variant="ghost" size="icon" onClick={() => setLaunchTarget(c)} title="Relancer">
                                <Play className="h-4 w-4 text-green-600" />
                              </Button>
                            </>
                          )}
                          {(c.status === "running" || c.status === "completed") && (
                            <Button variant="ghost" size="icon" onClick={() => openStats(c)} title="Stats">
                              <BarChart3 className="h-4 w-4" />
                            </Button>
                          )}
                          {c.status !== "running" && (
                            <Button variant="ghost" size="icon" onClick={() => setDeleteTarget(c)} title="Supprimer">
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

      {/* Dialog : Créer */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nouvelle campagne</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Nom</Label>
              <Input
                placeholder="Ex : Prospection RH — Juin 2026"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Séquence</Label>
              <Select value={formSequenceId} onValueChange={setFormSequenceId}>
                <SelectTrigger>
                  <SelectValue placeholder="Choisir une séquence" />
                </SelectTrigger>
                <SelectContent>
                  {sequences.map((s) => (
                    <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Listes de contacts</Label>
              <div className="space-y-2">
                {brevoLists.map((list) => (
                  <label
                    key={list.id}
                    className="flex items-center gap-2 cursor-pointer rounded-lg border p-3 hover:bg-muted/50 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={formListIds.includes(list.id)}
                      onChange={() => toggleList(list.id)}
                      className="rounded"
                    />
                    <span className="flex-1 text-sm">{list.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {list.total_subscribers} contacts
                    </span>
                  </label>
                ))}
                {brevoLists.length === 0 && (
                  <p className="text-sm text-muted-foreground">Aucune liste trouvée dans Brevo</p>
                )}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button
              onClick={handleCreate}
              disabled={saving || !formName.trim() || !formSequenceId || formListIds.length === 0}
            >
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Créer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Lancer */}
      <Dialog open={launchTarget !== null} onOpenChange={(open) => { if (!open) setLaunchTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Lancer la campagne ?</DialogTitle>
            <DialogDescription>
              Les contacts des listes sélectionnées vont commencer à recevoir les emails de la séquence.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLaunchTarget(null)}>Annuler</Button>
            <Button onClick={handleLaunch}>Lancer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Stats */}
      <Dialog open={statsOpen} onOpenChange={setStatsOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Statistiques — {stats?.campaign_name}</DialogTitle>
          </DialogHeader>
          {loadingStats ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : stats ? (
            <div className="space-y-4">
              <div className="flex gap-4 text-sm">
                <div><span className="font-medium">{stats.total_recipients}</span> contacts</div>
                <Badge variant={STATUS_BADGE[stats.status]?.variant ?? "outline"}>
                  {STATUS_BADGE[stats.status]?.label ?? stats.status}
                </Badge>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Étape</TableHead>
                    <TableHead className="text-right">Envoyés</TableHead>
                    <TableHead className="text-right">Ouverts</TableHead>
                    <TableHead className="text-right">Cliqués</TableHead>
                    <TableHead className="text-right">Échoués</TableHead>
                    <TableHead className="text-right">Désinscrits</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stats.steps.map((step) => (
                    <>
                      <TableRow key={step.step_position}>
                        <TableCell>
                          <div>
                            <span className="font-medium">Jour {step.delay_days}</span>
                            {step.template_name && (
                              <span className="text-xs text-muted-foreground ml-2">
                                {step.template_name}
                              </span>
                            )}
                            {step.branches.length > 0 && !step.template_name && (
                              <span className="text-xs text-muted-foreground ml-2">
                                (branchement)
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-right">{step.sent}</TableCell>
                        <TableCell className="text-right">
                          {step.opened} <span className="text-xs text-muted-foreground">({pct(step.opened, step.sent)})</span>
                        </TableCell>
                        <TableCell className="text-right">
                          {step.clicked} <span className="text-xs text-muted-foreground">({pct(step.clicked, step.sent)})</span>
                        </TableCell>
                        <TableCell className="text-right">{step.bounced}</TableCell>
                        <TableCell className="text-right">{step.unsubscribed}</TableCell>
                      </TableRow>
                      {step.branches.map((branch) => (
                        <TableRow key={`${step.step_position}-${branch.condition}`} className="bg-muted/30">
                          <TableCell className="pl-8">
                            <div className="flex items-center gap-1.5 text-xs">
                              <span className="text-muted-foreground">↳</span>
                              <Badge variant="outline" className="text-xs">
                                {CONDITION_LABELS[branch.condition] ?? branch.condition}
                              </Badge>
                              {branch.template_name && (
                                <span className="text-muted-foreground">{branch.template_name}</span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-right text-xs">{branch.sent}</TableCell>
                          <TableCell className="text-right text-xs">
                            {branch.opened} <span className="text-muted-foreground">({pct(branch.opened, branch.sent)})</span>
                          </TableCell>
                          <TableCell className="text-right text-xs">
                            {branch.clicked} <span className="text-muted-foreground">({pct(branch.clicked, branch.sent)})</span>
                          </TableCell>
                          <TableCell className="text-right text-xs">{branch.bounced}</TableCell>
                          <TableCell className="text-right text-xs">{branch.unsubscribed}</TableCell>
                        </TableRow>
                      ))}
                    </>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>

      {/* Dialog : Supprimer */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer cette campagne ?</DialogTitle>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Annuler</Button>
            <Button variant="destructive" onClick={handleDelete}>Supprimer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
