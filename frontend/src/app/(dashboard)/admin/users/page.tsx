"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Crown,
  HelpCircle,
  Mail,
  MessageSquare,
  Search,
  Trash2,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
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
import { PLANS, getPlanLabel, type AnyPlanCode } from "@/lib/plans";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface WorkspaceMember {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  role_in_workspace: string;
  is_owner: boolean;
}

interface WorkspaceOrg {
  id: string;
  name: string;
  documents_count: number;
  members_count: number;
}

interface WorkspaceOverview {
  account_id: string;
  name: string;
  plan: string;
  plan_expires_at: string | null;
  created_at: string;
  owner_email: string;
  owner_name: string;
  organisations: WorkspaceOrg[];
  members: WorkspaceMember[];
  total_documents: number;
  total_questions: number;
}

interface OrphanUser {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  created_at: string;
}

interface WorkspacesResponse {
  workspaces: WorkspaceOverview[];
  orphan_users: OrphanUser[];
  totals: {
    users: number;
    workspaces: number;
    organisations: number;
    documents: number;
  };
}

/* ------------------------------------------------------------------ */
/*  Plan config                                                        */
/* ------------------------------------------------------------------ */

// Plan labels + badge styling come from the single source of truth in
// `@/lib/plans`. Never re-declare plan codes here — extend PLANS instead.

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function ClientsPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Expanded rows
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Delete user dialog
  const [deleteTarget, setDeleteTarget] = useState<{
    user_id: string;
    email: string;
  } | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Delete account dialog
  const [deleteAccount, setDeleteAccount] = useState<{
    account_id: string;
    name: string;
  } | null>(null);
  const [deleteAccountConfirm, setDeleteAccountConfirm] = useState("");
  const [deleteAccountLoading, setDeleteAccountLoading] = useState(false);

  // Plan change
  const [planEdit, setPlanEdit] = useState<{
    accountId: string;
    plan: string;
  } | null>(null);
  const [planDuration, setPlanDuration] = useState("3");
  const [planSaving, setPlanSaving] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const params = debouncedSearch
        ? `?search=${encodeURIComponent(debouncedSearch)}`
        : "";
      const res = await apiFetch<WorkspacesResponse>(
        `/admin/workspaces/${params}`,
        { token },
      );
      setData(res);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Erreur lors du chargement",
      );
    } finally {
      setLoading(false);
    }
  }, [token, debouncedSearch]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDeleteUser = async () => {
    if (!deleteTarget || !token) return;
    setDeleteLoading(true);
    try {
      await apiFetch(`/admin/users/${deleteTarget.user_id}`, {
        method: "DELETE",
        token,
      });
      toast.success(`${deleteTarget.email} supprimé`);
      setDeleteTarget(null);
      fetchData();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Impossible de supprimer cet utilisateur",
      );
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!deleteAccount || !token) return;
    setDeleteAccountLoading(true);
    try {
      await apiFetch(`/admin/users/accounts/${deleteAccount.account_id}`, {
        method: "DELETE",
        token,
      });
      toast.success(`Client "${deleteAccount.name}" supprimé`);
      setDeleteAccount(null);
      setDeleteAccountConfirm("");
      fetchData();
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : "Impossible de supprimer ce client",
      );
    } finally {
      setDeleteAccountLoading(false);
    }
  };

  const handlePlanConfirm = async () => {
    if (!planEdit || !token) return;
    setPlanSaving(true);
    try {
      await apiFetch(`/admin/users/accounts/${planEdit.accountId}/plan`, {
        method: "PUT",
        token,
        body: JSON.stringify({
          plan: planEdit.plan,
          duration_months:
            planEdit.plan === "invite" ? Number(planDuration) : null,
        }),
      });
      toast.success(`Plan mis à jour : ${planEdit.plan}`);
      setPlanEdit(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setPlanSaving(false);
    }
  };

  const fmtDate = (iso: string) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Clients</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gestion des comptes clients, plans et membres.
        </p>
      </div>

      {/* Stats */}
      {data && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard
            icon={Crown}
            label="Clients"
            value={data.totals.workspaces}
          />
          <StatCard
            icon={Users}
            label="Utilisateurs"
            value={data.totals.users}
          />
          <StatCard
            icon={Building2}
            label="Organisations"
            value={data.totals.organisations}
          />
          <StatCard
            icon={MessageSquare}
            label="Documents"
            value={data.totals.documents}
          />
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Rechercher par nom, email, organisation..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Main table */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !data || data.workspaces.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          {debouncedSearch
            ? "Aucun résultat pour cette recherche."
            : "Aucun client."}
        </p>
      ) : (
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Client</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Propriétaire</TableHead>
                <TableHead className="text-center">Orgs</TableHead>
                <TableHead className="text-center">Membres</TableHead>
                <TableHead>Inscrit le</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.workspaces.map((ws) => {
                const isExpanded = expandedIds.has(ws.account_id);
                const planMeta = (ws.plan in PLANS)
                  ? PLANS[ws.plan as AnyPlanCode]
                  : null;
                const plan = {
                  label: planMeta?.label ?? ws.plan,
                  className: planMeta?.badgeClassName ?? "",
                };

                return (
                  <>
                    {/* Client row */}
                    <TableRow
                      key={ws.account_id}
                      className="cursor-pointer hover:bg-muted/50"
                      onClick={() => toggleExpand(ws.account_id)}
                    >
                      <TableCell className="px-2">
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        )}
                      </TableCell>
                      <TableCell className="font-medium">
                        {ws.name}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`rounded-full text-xs ${plan.className}`}
                        >
                          {plan.label}
                        </Badge>
                        {ws.plan === "invite" && ws.plan_expires_at && (
                          <span className="ml-1.5 text-[10px] text-muted-foreground">
                            exp. {fmtDate(ws.plan_expires_at)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="text-sm">{ws.owner_email}</span>
                          <span className="text-xs text-muted-foreground">
                            {ws.owner_name}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        {ws.organisations.length}
                      </TableCell>
                      <TableCell className="text-center">
                        {ws.members.length}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {fmtDate(ws.created_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div
                          className="flex items-center justify-end gap-2"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Select
                            value=""
                            onValueChange={(v) =>
                              setPlanEdit({
                                accountId: ws.account_id,
                                plan: v,
                              })
                            }
                          >
                            <SelectTrigger className="h-7 w-[110px] text-xs">
                              <SelectValue placeholder="Plan" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="gratuit">
                                Gratuit
                              </SelectItem>
                              <SelectItem value="invite">
                                Invité
                              </SelectItem>
                              <SelectItem value="vip">VIP</SelectItem>
                            </SelectContent>
                          </Select>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() =>
                              setDeleteAccount({
                                account_id: ws.account_id,
                                name: ws.name,
                              })
                            }
                            title="Supprimer le client"
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <TableRow key={`${ws.account_id}-detail`}>
                        <TableCell />
                        <TableCell colSpan={7} className="bg-muted/30 py-3">
                          <div className="space-y-4">
                            {/* Organisations */}
                            {ws.organisations.length > 0 && (
                              <div>
                                <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                                  Organisations
                                </p>
                                <div className="space-y-1 ml-2">
                                  {ws.organisations.map((org) => (
                                    <div
                                      key={org.id}
                                      className="flex items-center gap-3 text-sm"
                                    >
                                      <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                                      <span className="font-medium">
                                        {org.name}
                                      </span>
                                      <span className="text-xs text-muted-foreground">
                                        {org.documents_count} docs,{" "}
                                        {org.members_count} membres
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Members */}
                            <div>
                              <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider">
                                Membres
                              </p>
                              <div className="space-y-1 ml-2">
                                {ws.members.map((m) => (
                                  <div
                                    key={m.user_id}
                                    className="flex items-center gap-3 text-sm group"
                                  >
                                    <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                                    <span>{m.email}</span>
                                    <span className="text-xs text-muted-foreground">
                                      ({m.full_name})
                                    </span>
                                    {m.is_owner ? (
                                      <Badge
                                        variant="outline"
                                        className="rounded-full border-amber-500 bg-amber-500/10 text-amber-600 text-[10px] px-1.5 py-0"
                                      >
                                        Propriétaire
                                      </Badge>
                                    ) : (
                                      <Badge
                                        variant="outline"
                                        className="rounded-full text-[10px] px-1.5 py-0"
                                      >
                                        {m.role_in_workspace === "manager"
                                          ? "Manager"
                                          : "Utilisateur"}
                                      </Badge>
                                    )}
                                    {!m.is_owner && (
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                                        onClick={() =>
                                          setDeleteTarget({
                                            user_id: m.user_id,
                                            email: m.email,
                                          })
                                        }
                                        title="Supprimer"
                                      >
                                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                                      </Button>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Orphan users */}
      {data && data.orphan_users.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <HelpCircle className="h-4 w-4" />
            Utilisateurs orphelins ({data.orphan_users.length})
          </h2>
          <Card>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Nom</TableHead>
                  <TableHead>Rôle</TableHead>
                  <TableHead>Inscrit le</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.orphan_users.map((u) => (
                  <TableRow key={u.user_id}>
                    <TableCell className="text-sm">{u.email}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {u.full_name}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className="rounded-full text-xs"
                      >
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {fmtDate(u.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {(
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() =>
                            setDeleteTarget({
                              user_id: u.user_id,
                              email: u.email,
                            })
                          }
                          title="Supprimer"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </div>
      )}

      {/* Delete confirmation */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer l&apos;utilisateur</DialogTitle>
            <DialogDescription>
              Voulez-vous vraiment supprimer{" "}
              <strong>{deleteTarget?.email}</strong> ? Ses conversations et
              messages seront supprimés. Les documents et organisations ne sont
              pas impactés.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Annuler
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteUser}
              disabled={deleteLoading}
            >
              {deleteLoading ? "Suppression..." : "Supprimer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete account confirmation (type name to confirm) */}
      <Dialog
        open={deleteAccount !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteAccount(null);
            setDeleteAccountConfirm("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer le client</DialogTitle>
            <DialogDescription>
              Cette action est <strong>irréversible</strong>. Toutes les
              organisations, documents, conversations et membres de{" "}
              <strong>{deleteAccount?.name}</strong> seront définitivement
              supprimés.
              <br />
              <br />
              Pour confirmer, tapez{" "}
              <strong className="text-foreground">
                {deleteAccount?.name}
              </strong>{" "}
              ci-dessous.
            </DialogDescription>
          </DialogHeader>
          <Input
            value={deleteAccountConfirm}
            onChange={(e) => setDeleteAccountConfirm(e.target.value)}
            placeholder={deleteAccount?.name}
          />
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setDeleteAccount(null);
                setDeleteAccountConfirm("");
              }}
            >
              Annuler
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteAccount}
              disabled={
                deleteAccountConfirm !== deleteAccount?.name ||
                deleteAccountLoading
              }
            >
              {deleteAccountLoading
                ? "Suppression..."
                : "Supprimer le client"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Plan change confirmation */}
      <Dialog
        open={planEdit !== null}
        onOpenChange={(open) => {
          if (!open) setPlanEdit(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Changer le plan</DialogTitle>
            <DialogDescription>
              Passer ce client en{" "}
              <strong>
                {planEdit && getPlanLabel(planEdit.plan)}
              </strong>{" "}
              ?
            </DialogDescription>
          </DialogHeader>
          {planEdit &&
            (() => {
              const currentWs = data?.workspaces.find(
                (w) => w.account_id === planEdit.accountId,
              );
              const hasCommercialSub =
                currentWs !== undefined &&
                ["solo", "equipe", "groupe"].includes(currentWs.plan);
              if (!hasCommercialSub) return null;
              return (
                <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
                  <p className="font-medium text-destructive">
                    Ce client a un abonnement Stripe actif.
                  </p>
                  <p className="text-muted-foreground mt-1">
                    L&apos;abonnement Stripe sera{" "}
                    <strong>résilié immédiatement</strong> (sans remboursement)
                    et les add-ons retirés avant d&apos;appliquer le plan{" "}
                    <strong>{getPlanLabel(planEdit.plan)}</strong>.
                  </p>
                </div>
              );
            })()}
          {planEdit?.plan === "invite" && (
            <div className="flex items-center gap-3">
              <span className="text-sm">Durée :</span>
              <Select value={planDuration} onValueChange={setPlanDuration}>
                <SelectTrigger className="h-8 w-[100px] text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 mois</SelectItem>
                  <SelectItem value="2">2 mois</SelectItem>
                  <SelectItem value="3">3 mois</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setPlanEdit(null)}>
              Annuler
            </Button>
            <Button onClick={handlePlanConfirm} disabled={planSaving}>
              {planSaving ? "..." : "Confirmer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Stat card                                                          */
/* ------------------------------------------------------------------ */

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 pt-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <p className="text-2xl font-semibold">{value}</p>
          <p className="text-xs text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}
