"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Loader2, Plus, Play, Pause, RotateCcw, Trash2, BarChart3, Layers, X } from "lucide-react";
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

interface CampaignWave {
  id: string;
  number: number;
  scheduled_at: string;
  recipient_count: number;
  sent_count: number;
  done_count: number;
  status: string;
}

interface WavesOverview {
  campaign_id: string;
  status: string;
  total_recipients: number;
  pending_count: number;
  daily_limit: number;
  wave_max_size: number;
  waves: CampaignWave[];
}

interface WaveContact {
  email: string;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
}

const WAVE_STATUS: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
  scheduled: { label: "Programmée", variant: "outline" },
  sending: { label: "En cours", variant: "default" },
  done: { label: "Terminée", variant: "secondary" },
};

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

  const [wavesTarget, setWavesTarget] = useState<EmailCampaign | null>(null);
  const [waves, setWaves] = useState<WavesOverview | null>(null);
  const [loadingWaves, setLoadingWaves] = useState(false);
  const [waveCount, setWaveCount] = useState(100);
  const [waveDate, setWaveDate] = useState("");
  const [schedulingWave, setSchedulingWave] = useState(false);
  const [previewContacts, setPreviewContacts] = useState<WaveContact[]>([]);
  const [showPreview, setShowPreview] = useState(false);
  const [expandedWaveId, setExpandedWaveId] = useState<string | null>(null);
  const [waveContacts, setWaveContacts] = useState<WaveContact[]>([]);
  const [loadingWaveContacts, setLoadingWaveContacts] = useState(false);

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
      toast.success("Contacts chargés — programmez vos envois via « Vagues »");
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

  const loadWaves = useCallback(async (campaignId: string) => {
    if (!token) return;
    setLoadingWaves(true);
    try {
      const data = await apiFetch<WavesOverview>(
        `/admin/emailing/campaigns/${campaignId}/waves`,
        { token },
      );
      setWaves(data);
      setWaveCount(Math.min(100, data.pending_count) || 100);
    } catch {
      toast.error("Erreur lors du chargement des vagues");
    } finally {
      setLoadingWaves(false);
    }
  }, [token]);

  const loadPreview = useCallback(async (campaignId: string) => {
    if (!token) return;
    try {
      const data = await apiFetch<WaveContact[]>(
        `/admin/emailing/campaigns/${campaignId}/waves/preview?count=100`,
        { token },
      );
      setPreviewContacts(data);
    } catch {
      // l'aperçu n'est pas critique, on reste silencieux
    }
  }, [token]);

  function openWaves(campaign: EmailCampaign) {
    setWavesTarget(campaign);
    setWaveDate("");
    setShowPreview(false);
    setExpandedWaveId(null);
    loadWaves(campaign.id);
    loadPreview(campaign.id);
  }

  async function handleScheduleWave() {
    if (!token || !wavesTarget || !waveDate || waveCount < 1) return;
    setSchedulingWave(true);
    try {
      await apiFetch(`/admin/emailing/campaigns/${wavesTarget.id}/waves`, {
        method: "POST",
        token,
        // datetime-local est en heure locale : on l'envoie en UTC ISO.
        body: JSON.stringify({
          count: waveCount,
          scheduled_at: new Date(waveDate).toISOString(),
        }),
      });
      toast.success("Envoi programmé");
      setWaveDate("");
      await loadWaves(wavesTarget.id);
      await loadPreview(wavesTarget.id);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setSchedulingWave(false);
    }
  }

  async function handleCancelWave(waveId: string) {
    if (!token || !wavesTarget) return;
    try {
      await apiFetch(`/admin/emailing/campaigns/${wavesTarget.id}/waves/${waveId}`, {
        method: "DELETE",
        token,
      });
      toast.success("Vague annulée");
      if (expandedWaveId === waveId) setExpandedWaveId(null);
      await loadWaves(wavesTarget.id);
      await loadPreview(wavesTarget.id);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function toggleWaveContacts(waveId: string) {
    if (expandedWaveId === waveId) {
      setExpandedWaveId(null);
      return;
    }
    if (!token || !wavesTarget) return;
    setExpandedWaveId(waveId);
    setWaveContacts([]);
    setLoadingWaveContacts(true);
    try {
      const data = await apiFetch<WaveContact[]>(
        `/admin/emailing/campaigns/${wavesTarget.id}/waves/${waveId}/contacts`,
        { token },
      );
      setWaveContacts(data);
    } catch {
      toast.error("Erreur lors du chargement des contacts");
    } finally {
      setLoadingWaveContacts(false);
    }
  }

  const contactLabel = (c: WaveContact) => {
    const name = [c.first_name, c.last_name].filter(Boolean).join(" ");
    return name ? `${name} · ${c.email}` : c.email;
  };

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("fr-FR", {
      day: "numeric", month: "short", year: "numeric",
    });

  const fmtDateTime = (d: string) =>
    new Date(d).toLocaleString("fr-FR", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
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
                            <Button variant="ghost" size="icon" onClick={() => setLaunchTarget(c)} title="Charger les contacts">
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
                              <Button variant="ghost" size="icon" onClick={() => setLaunchTarget(c)} title="Recharger les contacts">
                                <Play className="h-4 w-4 text-green-600" />
                              </Button>
                            </>
                          )}
                          {(c.status === "running" || c.status === "paused" || c.status === "completed") && (
                            <Button variant="ghost" size="icon" onClick={() => openWaves(c)} title="Programmer les envois (vagues)">
                              <Layers className="h-4 w-4" />
                            </Button>
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
            <DialogTitle>Charger les contacts ?</DialogTitle>
            <DialogDescription>
              Les contacts des listes sélectionnées sont mis en attente.{" "}
              <strong>Aucun mail n&apos;est envoyé à cette étape.</strong> Ensuite, via
              l&apos;icône « Vagues », vous choisissez quand et combien partent.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLaunchTarget(null)}>Annuler</Button>
            <Button onClick={handleLaunch}>Charger les contacts</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Stats */}
      <Dialog open={statsOpen} onOpenChange={setStatsOpen}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Statistiques — {stats?.campaign_name}</DialogTitle>
          </DialogHeader>
          {loadingStats ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : stats ? (
            // min-w-0 : laisse le conteneur rétrécir pour que la table scrolle
            // horizontalement au lieu de déborder hors de la fenêtre.
            <div className="space-y-4 min-w-0">
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
                            <div className="flex flex-wrap items-center gap-1.5 text-xs">
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

      {/* Dialog : Vagues d'envoi */}
      <Dialog
        open={wavesTarget !== null}
        onOpenChange={(open) => { if (!open) { setWavesTarget(null); setWaves(null); } }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Vagues d&apos;envoi — {wavesTarget?.name}</DialogTitle>
            <DialogDescription>
              {waves
                ? `${waves.pending_count} contact(s) en attente sur ${waves.total_recipients}. Maximum ${waves.wave_max_size} par envoi, ${waves.daily_limit}/jour (limite Brevo).`
                : "Chargement…"}
            </DialogDescription>
          </DialogHeader>
          {loadingWaves ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : waves ? (
            <div className="space-y-5">
              {/* Bloc 1 : programmer un envoi */}
              {wavesTarget?.status === "running" && waves.pending_count > 0 && (
                <div className="rounded-lg border p-3 space-y-3">
                  <p className="text-sm font-medium">Programmer un envoi</p>
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs">Combien de contacts</Label>
                      <Input
                        type="number"
                        min={1}
                        max={Math.min(waves.wave_max_size, waves.pending_count)}
                        value={waveCount}
                        onChange={(e) => setWaveCount(Number(e.target.value))}
                        className="w-24"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Quand (date et heure)</Label>
                      <Input
                        type="datetime-local"
                        value={waveDate}
                        onChange={(e) => setWaveDate(e.target.value)}
                        className="w-56"
                      />
                    </div>
                    <Button
                      onClick={handleScheduleWave}
                      disabled={schedulingWave || !waveDate || waveCount < 1}
                    >
                      {schedulingWave && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                      Programmer cet envoi
                    </Button>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowPreview((v) => !v)}
                    className="text-xs text-primary underline-offset-2 hover:underline"
                  >
                    {showPreview ? "Masquer" : "Voir"} les{" "}
                    {Math.min(waveCount, previewContacts.length)} contacts qui partiront
                  </button>
                  {showPreview && (
                    <div className="max-h-40 overflow-auto rounded border bg-muted/30 p-2 text-xs space-y-0.5">
                      {previewContacts.length === 0 ? (
                        <div className="text-muted-foreground">Aucun contact en attente.</div>
                      ) : (
                        previewContacts.slice(0, waveCount).map((c, i) => (
                          <div key={i} className="text-muted-foreground">{contactLabel(c)}</div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              )}
              {wavesTarget?.status === "running" && waves.pending_count === 0 && (
                <p className="text-sm text-muted-foreground">
                  Tous les contacts ont été répartis en envois.
                </p>
              )}

              {/* Bloc 2 : envois programmés / faits */}
              {waves.waves.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Aucun envoi programmé pour l&apos;instant.
                </p>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">
                    Envois programmés / faits
                  </p>
                  {waves.waves.map((w) => {
                    const badge = WAVE_STATUS[w.status] ?? { label: w.status, variant: "outline" as const };
                    const expanded = expandedWaveId === w.id;
                    return (
                      <div key={w.id} className="rounded-lg border">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 p-2.5 text-sm">
                          <span className="font-medium">Envoi {w.number}</span>
                          <span className="text-muted-foreground">· {w.recipient_count} contacts</span>
                          <span className="text-muted-foreground">· {fmtDateTime(w.scheduled_at)}</span>
                          <Badge variant={badge.variant} className="ml-1">{badge.label}</Badge>
                          <div className="ml-auto flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => toggleWaveContacts(w.id)}
                            >
                              {expanded ? "Masquer" : "Voir la liste"}
                            </Button>
                            {w.status === "scheduled" && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => handleCancelWave(w.id)}
                                title="Annuler cet envoi"
                              >
                                <X className="h-4 w-4 text-destructive" />
                              </Button>
                            )}
                          </div>
                        </div>
                        {expanded && (
                          <div className="border-t max-h-40 overflow-auto bg-muted/30 p-2 text-xs space-y-0.5">
                            {loadingWaveContacts ? (
                              <div className="flex justify-center py-2">
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                              </div>
                            ) : (
                              waveContacts.map((c, i) => (
                                <div key={i} className="text-muted-foreground">{contactLabel(c)}</div>
                              ))
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
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
