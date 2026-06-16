"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Copy,
  Gift,
  Loader2,
  Plus,
  Trash2,
  Eye,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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

interface PlanInvitation {
  id: string;
  token: string;
  label: string;
  plan: string;
  duration_months: number;
  email: string | null;
  max_uses: number | null;
  use_count: number;
  status: string;
  expires_at: string;
  created_at: string;
  shareable_url: string | null;
}

interface Redemption {
  id: string;
  account_id: string;
  user_id: string;
  user_email: string | null;
  user_name: string | null;
  redeemed_at: string;
}

interface PlanInvitationDetail extends PlanInvitation {
  redemptions: Redemption[];
}

const STATUS_BADGE: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  active: { label: "Actif", variant: "default" },
  exhausted: { label: "Épuisé", variant: "secondary" },
  expired: { label: "Expiré", variant: "outline" },
  revoked: { label: "Révoqué", variant: "destructive" },
};

export default function AdminPlanInvitationsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [invitations, setInvitations] = useState<PlanInvitation[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [formLabel, setFormLabel] = useState("");
  const [formDuration, setFormDuration] = useState("1");
  const [formEmail, setFormEmail] = useState("");
  const [formMaxUses, setFormMaxUses] = useState("");
  const [formExpiresDays, setFormExpiresDays] = useState("30");

  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<PlanInvitationDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [revokeTarget, setRevokeTarget] = useState<PlanInvitation | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("active");

  const fetchList = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = statusFilter && statusFilter !== "all"
        ? `?status=${statusFilter}`
        : "";
      const data = await apiFetch<{ items: PlanInvitation[]; total: number }>(
        `/admin/plan-invitations${params}`,
        { token },
      );
      setInvitations(data.items);
      setTotal(data.total);
    } catch {
      toast.error("Erreur lors du chargement des invitations plan");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchList();
  }, [fetchList, statusFilter]);

  async function handleCreate() {
    if (!token || !formLabel.trim()) return;
    setCreating(true);
    try {
      const body: Record<string, unknown> = {
        label: formLabel.trim(),
        plan: "invite",
        duration_months: parseInt(formDuration),
        expires_in_days: parseInt(formExpiresDays),
      };
      if (formEmail.trim()) body.email = formEmail.trim();
      if (formMaxUses.trim()) body.max_uses = parseInt(formMaxUses);

      const created = await apiFetch<PlanInvitation>(
        "/admin/plan-invitations",
        {
          method: "POST",
          token,
          body: JSON.stringify(body),
        },
      );

      if (created.shareable_url) {
        await navigator.clipboard.writeText(created.shareable_url);
        toast.success("Lien créé et copié dans le presse-papiers");
      } else {
        toast.success("Lien créé");
      }

      setCreateOpen(false);
      resetForm();
      fetchList();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors de la création",
      );
    } finally {
      setCreating(false);
    }
  }

  function resetForm() {
    setFormLabel("");
    setFormDuration("1");
    setFormEmail("");
    setFormMaxUses("");
    setFormExpiresDays("30");
  }

  async function handleViewDetail(inv: PlanInvitation) {
    if (!token) return;
    setDetailOpen(true);
    setLoadingDetail(true);
    try {
      const data = await apiFetch<PlanInvitationDetail>(
        `/admin/plan-invitations/${inv.id}`,
        { token },
      );
      setDetail(data);
    } catch {
      toast.error("Erreur lors du chargement du détail");
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleRevoke() {
    if (!token || !revokeTarget) return;
    try {
      await apiFetch(`/admin/plan-invitations/${revokeTarget.id}`, {
        method: "DELETE",
        token,
      });
      toast.success("Lien révoqué");
      setRevokeTarget(null);
      fetchList();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors de la révocation",
      );
    }
  }

  function copyUrl(url: string) {
    navigator.clipboard.writeText(url);
    toast.success("Lien copié");
  }

  const fmt = (d: string) =>
    new Date(d).toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Liens promo</h1>
          <p className="text-sm text-muted-foreground">
            Créez et gérez les liens d&apos;invitation au plan Invité ({total} au total)
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Créer un lien
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v)}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Filtrer par statut" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Actifs</SelectItem>
            <SelectItem value="exhausted">Épuisés</SelectItem>
            <SelectItem value="expired">Expirés</SelectItem>
            <SelectItem value="revoked">Révoqués</SelectItem>
            <SelectItem value="all">Tous</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Label</TableHead>
                <TableHead>Lien</TableHead>
                <TableHead>Durée</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Utilisations</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Expire le</TableHead>
                <TableHead>Créé le</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8">
                    <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                  </TableCell>
                </TableRow>
              ) : invitations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
                    Aucun lien promo créé
                  </TableCell>
                </TableRow>
              ) : (
                invitations.map((inv) => {
                  const badge = STATUS_BADGE[inv.status] ?? {
                    label: inv.status,
                    variant: "outline" as const,
                  };
                  return (
                    <TableRow key={inv.id}>
                      <TableCell className="font-medium">{inv.label}</TableCell>
                      <TableCell>
                        {inv.shareable_url ? (
                          <button
                            onClick={() => copyUrl(inv.shareable_url!)}
                            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors max-w-[200px]"
                            title={inv.shareable_url}
                          >
                            <code className="truncate">{inv.shareable_url.replace("https://app.aoriarh.fr", "")}</code>
                            <Copy className="h-3 w-3 shrink-0" />
                          </button>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>{inv.duration_months} mois</TableCell>
                      <TableCell className="text-muted-foreground">
                        {inv.email ?? "Ouvert"}
                      </TableCell>
                      <TableCell>
                        {inv.use_count}
                        {inv.max_uses !== null ? ` / ${inv.max_uses}` : ""}
                      </TableCell>
                      <TableCell>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </TableCell>
                      <TableCell>{fmt(inv.expires_at)}</TableCell>
                      <TableCell>{fmt(inv.created_at)}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleViewDetail(inv)}
                            title="Voir le détail"
                          >
                            <Eye className="h-4 w-4" />
                          </Button>
                          {inv.status === "active" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => setRevokeTarget(inv)}
                              title="Révoquer"
                            >
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

      {/* Dialog : Créer un lien */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nouveau lien promo</DialogTitle>
            <DialogDescription>
              Créez un lien d&apos;invitation au plan Invité. Le lien sera copié
              automatiquement.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                placeholder="Ex : Campagne CSE juin 2026"
                value={formLabel}
                onChange={(e) => setFormLabel(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Durée du plan</Label>
                <Select value={formDuration} onValueChange={setFormDuration}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 mois</SelectItem>
                    <SelectItem value="2">2 mois</SelectItem>
                    <SelectItem value="3">3 mois</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Expiration du lien</Label>
                <Select
                  value={formExpiresDays}
                  onValueChange={setFormExpiresDays}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="10">10 jours</SelectItem>
                    <SelectItem value="30">30 jours</SelectItem>
                    <SelectItem value="60">60 jours</SelectItem>
                    <SelectItem value="90">90 jours</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">
                Email (facultatif)
              </Label>
              <Input
                id="email"
                type="email"
                placeholder="Laisser vide = lien ouvert à tous"
                value={formEmail}
                onChange={(e) => setFormEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="maxUses">
                Nombre max d&apos;utilisations (facultatif)
              </Label>
              <Input
                id="maxUses"
                type="number"
                min="1"
                placeholder="Illimité par défaut"
                value={formMaxUses}
                onChange={(e) => setFormMaxUses(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setCreateOpen(false);
                resetForm();
              }}
            >
              Annuler
            </Button>
            <Button
              onClick={handleCreate}
              disabled={creating || !formLabel.trim()}
            >
              {creating ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Gift className="mr-2 h-4 w-4" />
              )}
              Créer le lien
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog : Détail d'un lien */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{detail?.label ?? "Détail"}</DialogTitle>
            {detail?.shareable_url && (
              <div
                className="flex items-center gap-2 mt-1 cursor-pointer"
                onClick={() => copyUrl(detail.shareable_url!)}
                title="Cliquer pour copier"
              >
                <code className="text-xs bg-muted px-2 py-1 rounded whitespace-nowrap">
                  {detail.shareable_url}
                </code>
                <Copy className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </div>
            )}
          </DialogHeader>
          {loadingDetail ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : detail?.redemptions && detail.redemptions.length > 0 ? (
            <div className="space-y-2">
              <p className="text-sm font-medium">
                Activations ({detail.redemptions.length})
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Utilisateur</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.redemptions.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{r.user_name ?? "-"}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {r.user_email ?? "-"}
                      </TableCell>
                      <TableCell>{fmt(r.redeemed_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground py-4 text-center">
              Aucune activation pour ce lien
            </p>
          )}
        </DialogContent>
      </Dialog>

      {/* Dialog : Confirmer la révocation */}
      <Dialog
        open={revokeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRevokeTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Révoquer ce lien ?</DialogTitle>
            <DialogDescription>
              Le lien &laquo;&nbsp;{revokeTarget?.label}&nbsp;&raquo; ne sera
              plus utilisable. Les plans déjà activés ne sont pas affectés.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleRevoke}>
              Révoquer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
