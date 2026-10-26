"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  AdminLoadError,
  AdminPageHeader,
} from "@/components/admin/page-header";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  HelpCircle,
  Mail,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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

interface OrgCcn {
  idcc: string;
  titre: string | null;
  status: string;
  use_custom: boolean;
}

interface WorkspaceOrg {
  id: string;
  name: string;
  documents_count: number;
  members_count: number;
  idccs: OrgCcn[];
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

export function ClientAccounts({
  accountId,
  onChanged,
  onDeleted,
}: {
  accountId?: string;
  onChanged?: () => void;
  onDeleted?: () => void;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Expanded rows
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    new Set(accountId ? [accountId] : [])
  );

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
    setError(false);
    try {
      const query = new URLSearchParams();
      if (debouncedSearch) query.set("search", debouncedSearch);
      if (accountId) query.set("account_id", accountId);
      const params = `?${query}`;
      const res = await apiFetch<WorkspacesResponse>(
        `/admin/workspaces/${params}`,
        { token }
      );
      setData(res);
    } catch (err) {
      setError(true);
      toast.error(
        err instanceof Error ? err.message : "Erreur lors du chargement"
      );
    } finally {
      setLoading(false);
    }
  }, [token, debouncedSearch, accountId]);

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
          : "Impossible de supprimer cet utilisateur"
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
      if (onDeleted) onDeleted();
      else void fetchData();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Impossible de supprimer ce client"
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
      void fetchData();
      onChanged?.();
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
      {!accountId && (
        <>
          <AdminPageHeader
            section="Clients"
            title="Comptes & membres"
            description="Gérez les accès, les organisations et les offres des comptes clients."
            actions={
              <Button variant="outline" asChild>
                <Link
                  href={
                    session?.user?.staff_role === "tech"
                      ? "/admin/tools"
                      : "/admin/clients"
                  }
                >
                  Retour
                </Link>
              </Button>
            }
          />
          <div className="relative max-w-md">
            <Search
              aria-hidden="true"
              className="text-muted-foreground absolute top-3 left-3 size-4"
            />
            <Input
              aria-label="Rechercher un compte ou un membre"
              placeholder="Nom, email, organisation…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-10 pl-9"
            />
          </div>
        </>
      )}
      {error && <AdminLoadError onRetry={fetchData} />}

      {/* Main table */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : error ? null : !data || data.workspaces.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center">
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
                const planMeta =
                  ws.plan in PLANS ? PLANS[ws.plan as AnyPlanCode] : null;
                const plan = {
                  label: planMeta?.label ?? ws.plan,
                  className: planMeta?.badgeClassName ?? "",
                };

                return (
                  <Fragment key={ws.account_id}>
                    {/* Client row */}
                    <TableRow
                      key={ws.account_id}
                      className="hover:bg-muted/50 cursor-pointer"
                      onClick={() => toggleExpand(ws.account_id)}
                    >
                      <TableCell className="px-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-9"
                          aria-label={`${isExpanded ? "Replier" : "Afficher"} les membres et organisations de ${ws.name}`}
                          aria-expanded={isExpanded}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(ws.account_id);
                          }}
                        >
                          {isExpanded ? (
                            <ChevronDown className="size-4" />
                          ) : (
                            <ChevronRight className="size-4" />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell className="font-medium">{ws.name}</TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={`rounded-full text-xs ${plan.className}`}
                        >
                          {plan.label}
                        </Badge>
                        {ws.plan === "invite" && ws.plan_expires_at && (
                          <span className="text-muted-foreground ml-1.5 text-[10px]">
                            exp. {fmtDate(ws.plan_expires_at)}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="text-sm">{ws.owner_email}</span>
                          <span className="text-muted-foreground text-xs">
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
                      <TableCell className="text-muted-foreground text-sm">
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
                              <SelectItem value="gratuit">Gratuit</SelectItem>
                              <SelectItem value="invite">Invité</SelectItem>
                              <SelectItem value="vip">VIP</SelectItem>
                              <SelectItem value="solo">Solo</SelectItem>
                              <SelectItem value="equipe">Équipe</SelectItem>
                              <SelectItem value="groupe">Groupe</SelectItem>
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
                            <Trash2 className="text-destructive h-3.5 w-3.5" />
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
                                <p className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase">
                                  Organisations
                                </p>
                                <div className="ml-2 space-y-2">
                                  {ws.organisations.map((org) => (
                                    <div key={org.id} className="space-y-1">
                                      <div className="flex items-center gap-3 text-sm">
                                        <Building2 className="text-muted-foreground h-3.5 w-3.5" />
                                        <span className="font-medium">
                                          {org.name}
                                        </span>
                                        <span className="text-muted-foreground text-xs">
                                          {org.documents_count} docs,{" "}
                                          {org.members_count} membres
                                        </span>
                                      </div>
                                      {org.idccs.length > 0 ? (
                                        <div className="ml-6 flex flex-wrap gap-1">
                                          {org.idccs.map((c) => (
                                            <Badge
                                              key={c.idcc}
                                              variant="outline"
                                              className={
                                                c.status === "ready"
                                                  ? "px-1.5 py-0 font-mono text-[10px]"
                                                  : "px-1.5 py-0 font-mono text-[10px] opacity-60"
                                              }
                                              title={`${c.titre ?? ""} — statut: ${c.status}${c.use_custom ? " (custom)" : ""}`}
                                            >
                                              IDCC {c.idcc}
                                              {c.titre && (
                                                <span className="ml-1 font-sans font-normal">
                                                  — {c.titre}
                                                </span>
                                              )}
                                              {c.status !== "ready" && (
                                                <span className="text-muted-foreground ml-1">
                                                  ({c.status})
                                                </span>
                                              )}
                                            </Badge>
                                          ))}
                                        </div>
                                      ) : (
                                        <div className="text-muted-foreground ml-6 text-[10px] italic">
                                          Aucune CCN installée
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Members */}
                            <div>
                              <p className="text-muted-foreground mb-2 text-xs font-semibold tracking-wider uppercase">
                                Membres
                              </p>
                              <div className="ml-2 space-y-1">
                                {ws.members.map((m) => (
                                  <div
                                    key={m.user_id}
                                    className="group flex items-center gap-3 text-sm"
                                  >
                                    <Mail className="text-muted-foreground h-3.5 w-3.5" />
                                    <span>{m.email}</span>
                                    <span className="text-muted-foreground text-xs">
                                      ({m.full_name})
                                    </span>
                                    {m.is_owner ? (
                                      <Badge
                                        variant="outline"
                                        className="rounded-full border-amber-500 bg-amber-500/10 px-1.5 py-0 text-[10px] text-amber-600"
                                      >
                                        Propriétaire
                                      </Badge>
                                    ) : (
                                      <Badge
                                        variant="outline"
                                        className="rounded-full px-1.5 py-0 text-[10px]"
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
                                        className="h-6 w-6 opacity-0 transition-opacity group-hover:opacity-100"
                                        onClick={() =>
                                          setDeleteTarget({
                                            user_id: m.user_id,
                                            email: m.email,
                                          })
                                        }
                                        title="Supprimer"
                                      >
                                        <Trash2 className="text-destructive h-3.5 w-3.5" />
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
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Orphan users */}
      {!accountId && data && data.orphan_users.length > 0 && (
        <div>
          <h2 className="text-muted-foreground mb-2 flex items-center gap-2 text-sm font-semibold">
            <HelpCircle className="h-4 w-4" />
            Utilisateurs sans compte ({data.orphan_users.length})
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
                    <TableCell className="text-muted-foreground text-sm">
                      {u.full_name}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="rounded-full text-xs">
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {fmtDate(u.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {
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
                          <Trash2 className="text-destructive h-3.5 w-3.5" />
                        </Button>
                      }
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
              {deleteAccountLoading ? "Suppression..." : "Supprimer le client"}
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
              <strong>{planEdit && getPlanLabel(planEdit.plan)}</strong> ?
            </DialogDescription>
          </DialogHeader>
          {planEdit &&
            (() => {
              const currentWs = data?.workspaces.find(
                (w) => w.account_id === planEdit.accountId
              );
              const hasCommercialSub =
                currentWs !== undefined &&
                ["solo", "equipe", "groupe"].includes(currentWs.plan);
              const targetIsTechnical = ["gratuit", "invite", "vip"].includes(
                planEdit.plan
              );
              const targetIsCommercial = ["solo", "equipe", "groupe"].includes(
                planEdit.plan
              );

              if (hasCommercialSub && targetIsTechnical) {
                return (
                  <div className="border-destructive/40 bg-destructive/5 rounded-md border p-3 text-sm">
                    <p className="text-destructive font-medium">
                      Ce client a un abonnement Stripe actif.
                    </p>
                    <p className="text-muted-foreground mt-1">
                      L&apos;abonnement Stripe sera{" "}
                      <strong>résilié immédiatement</strong> (sans
                      remboursement) et les add-ons retirés avant
                      d&apos;appliquer le plan{" "}
                      <strong>{getPlanLabel(planEdit.plan)}</strong>.
                    </p>
                  </div>
                );
              }
              if (hasCommercialSub && targetIsCommercial) {
                return (
                  <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
                    <p className="font-medium text-amber-700">
                      Changement de plan commercial côté Stripe.
                    </p>
                    <p className="text-muted-foreground mt-1">
                      L&apos;abonnement Stripe sera{" "}
                      <strong>
                        modifié vers {getPlanLabel(planEdit.plan)}
                      </strong>{" "}
                      avec un prorata appliqué sur la prochaine facture. Un{" "}
                      <strong>downgrade trop petit</strong> (par ex.{" "}
                      {getPlanLabel(planEdit.plan)} mais le client a plus
                      d&apos;orgs/users/docs que le plan n&apos;en autorise)
                      sera bloqué en 409.
                    </p>
                  </div>
                );
              }
              if (!hasCommercialSub && targetIsCommercial) {
                return (
                  <div className="border-destructive/40 bg-destructive/5 rounded-md border p-3 text-sm">
                    <p className="text-destructive font-medium">
                      Impossible d&apos;assigner un plan commercial sans Stripe.
                    </p>
                    <p className="text-muted-foreground mt-1">
                      Ce compte n&apos;a pas d&apos;abonnement Stripe actif :
                      l&apos;admin ne peut pas souscrire à la place du client
                      (pas de moyen de paiement). Le client doit souscrire
                      lui-même depuis sa page /billing.
                    </p>
                  </div>
                );
              }
              return null;
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
