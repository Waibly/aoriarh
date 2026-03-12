"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { Search, Users, Building2, Crown, Gift, User as UserIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

interface UserOrgItem {
  organisation_id: string;
  organisation_name: string;
  role_in_org: string;
}

interface AdminUserItem {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  organisations: UserOrgItem[];
  account_id: string | null;
  account_name: string | null;
  plan: string | null;
  plan_expires_at: string | null;
}

interface UserListResponse {
  items: AdminUserItem[];
  total: number;
  page: number;
  page_size: number;
}

const roleBadge: Record<string, { label: string; className: string }> = {
  admin: { label: "Admin", className: "rounded-full border-amber-400 bg-amber-50 text-amber-700 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-300" },
  manager: { label: "Manager", className: "rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]" },
  user: { label: "Utilisateur", className: "rounded-full" },
};

const planStyles: Record<string, { label: string; icon: typeof Crown; badgeClass: string }> = {
  gratuit: { label: "Gratuit", icon: UserIcon, badgeClass: "rounded-full" },
  invite: { label: "Invité", icon: Gift, badgeClass: "rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]" },
  vip: { label: "VIP", icon: Crown, badgeClass: "rounded-full border-amber-400 bg-amber-50 text-amber-700 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-300" },
};

function orgRoleLabel(role: string): string {
  switch (role) {
    case "manager": return "Manager";
    case "user": return "Membre";
    default: return role;
  }
}

function PlanBadge({ plan, planExpiresAt }: { plan: string | null; planExpiresAt: string | null }) {
  const style = planStyles[plan ?? "gratuit"] ?? planStyles.gratuit;
  const Icon = style.icon;

  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant="outline" className={style.badgeClass}>
        <Icon className="mr-1 size-3" />
        {style.label}
      </Badge>
      {plan === "invite" && planExpiresAt && (
        <span className="text-xs text-muted-foreground">
          Expire le {new Date(planExpiresAt).toLocaleDateString("fr-FR")}
        </span>
      )}
    </span>
  );
}

export default function AdminUsersPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<UserListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 50;

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [userToDelete, setUserToDelete] = useState<AdminUserItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Plan dialog state
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);
  const [selectedAccountName, setSelectedAccountName] = useState<string>("");
  const [selectedPlan, setSelectedPlan] = useState<string>("gratuit");
  const [selectedDuration, setSelectedDuration] = useState<string>("1");
  const [planSaving, setPlanSaving] = useState(false);

  const fetchUsers = useCallback(async () => {
    if (!token) return;
    try {
      const res = await apiFetch<UserListResponse>(
        `/admin/users/?page=${page}&page_size=${PAGE_SIZE}`,
        { token },
      );
      setData(res);
    } catch {
      toast.error("Erreur lors du chargement des utilisateurs");
    } finally {
      setLoading(false);
    }
  }, [token, page]);

  useEffect(() => {
    setLoading(true);
    fetchUsers();
  }, [fetchUsers]);

  const filteredItems = data?.items.filter((u) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      u.full_name.toLowerCase().includes(q) ||
      u.email.toLowerCase().includes(q) ||
      u.organisations.some((o) => o.organisation_name.toLowerCase().includes(q))
    );
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  function openPlanDialog(accountId: string, accountName: string, currentPlan: string) {
    setSelectedAccountId(accountId);
    setSelectedAccountName(accountName);
    setSelectedPlan(currentPlan);
    setSelectedDuration("1");
    setPlanDialogOpen(true);
  }

  async function handlePlanSubmit() {
    if (!token || !selectedAccountId) return;
    setPlanSaving(true);
    try {
      await apiFetch(`/admin/users/accounts/${selectedAccountId}/plan`, {
        token,
        method: "PUT",
        body: JSON.stringify({
          plan: selectedPlan,
          ...(selectedPlan === "invite" ? { duration_months: parseInt(selectedDuration) } : {}),
        }),
      });
      toast.success("Plan mis à jour");
      setPlanDialogOpen(false);
      fetchUsers();
      window.dispatchEvent(new Event("plan-updated"));
    } catch {
      toast.error("Erreur lors de la mise à jour du plan");
    } finally {
      setPlanSaving(false);
    }
  }

  function openDeleteDialog(user: AdminUserItem) {
    setUserToDelete(user);
    setDeleteDialogOpen(true);
  }

  async function handleDelete() {
    if (!token || !userToDelete) return;
    setDeleting(true);
    try {
      await apiFetch(`/admin/users/${userToDelete.id}`, {
        token,
        method: "DELETE",
      });
      toast.success(`${userToDelete.full_name} supprimé`);
      setDeleteDialogOpen(false);
      setUserToDelete(null);
      fetchUsers();
    } catch {
      toast.error("Erreur lors de la suppression");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Utilisateurs</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="size-5" />
            Tous les utilisateurs
          </CardTitle>
          <CardDescription>
            {data ? `${data.total} utilisateur${data.total > 1 ? "s" : ""} au total` : "Chargement..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4">
            <div className="relative max-w-sm">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Rechercher par nom ou email..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>

          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !filteredItems || filteredItems.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              {search ? "Aucun utilisateur trouvé." : "Aucun utilisateur pour le moment."}
            </p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Nom</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Rôle</TableHead>
                    <TableHead>Organisations</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Statut</TableHead>
                    <TableHead>Inscription</TableHead>
                    <TableHead className="w-10"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredItems!.map((user) => {
                    const badge = roleBadge[user.role] || roleBadge.user;
                    return (
                      <TableRow key={user.id}>
                        <TableCell className="font-medium text-sm">
                          {user.full_name}
                        </TableCell>
                        <TableCell className="text-sm">
                          {user.email}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={badge.className}>{badge.label}</Badge>
                        </TableCell>
                        <TableCell className="text-sm">
                          {user.organisations.length === 0 ? (
                            <span className="text-muted-foreground">Aucune</span>
                          ) : (
                            <Popover>
                              <PopoverTrigger asChild>
                                <button className="flex cursor-pointer items-center gap-1 hover:underline">
                                  <Building2 className="size-3.5 text-muted-foreground" />
                                  {user.organisations.length} org{user.organisations.length > 1 ? "s" : ""}
                                </button>
                              </PopoverTrigger>
                              <PopoverContent side="bottom" className="w-80">
                                <ul className="space-y-2">
                                  {user.organisations.map((o) => (
                                    <li key={o.organisation_id} className="flex items-center justify-between gap-3 text-sm">
                                      <span className="font-medium">{o.organisation_name}</span>
                                      <span className="text-xs text-muted-foreground">{orgRoleLabel(o.role_in_org)}</span>
                                    </li>
                                  ))}
                                </ul>
                              </PopoverContent>
                            </Popover>
                          )}
                        </TableCell>
                        <TableCell>
                          {user.account_id ? (
                            <button
                              onClick={() => openPlanDialog(user.account_id!, user.account_name ?? "—", user.plan ?? "gratuit")}
                              className="cursor-pointer"
                              title="Modifier le plan"
                            >
                              <PlanBadge plan={user.plan} planExpiresAt={user.plan_expires_at} />
                            </button>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {user.is_active ? (
                            <Badge variant="outline" className="rounded-full border-green-500 bg-green-500/10 text-green-600 dark:text-green-400">Actif</Badge>
                          ) : (
                            <Badge variant="outline" className="rounded-full border-red-500 bg-red-500/10 text-red-600 dark:text-red-400">Inactif</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                          {new Date(user.created_at).toLocaleDateString("fr-FR", {
                            day: "2-digit",
                            month: "2-digit",
                            year: "numeric",
                          })}
                        </TableCell>
                        <TableCell>
                          {user.role !== "admin" && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8 text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950"
                              onClick={() => openDeleteDialog(user)}
                            >
                              <Trash2 className="size-4" />
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t pt-4 mt-4">
                  <p className="text-sm text-muted-foreground">
                    {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data!.total)} sur {data!.total}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1}
                      onClick={() => setPage((p) => p - 1)}
                    >
                      Précédent
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      {page} / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      Suivant
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Plan Assignment Dialog */}
      <Dialog open={planDialogOpen} onOpenChange={setPlanDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Modifier le plan</DialogTitle>
            <DialogDescription>
              Compte : {selectedAccountName}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-6 py-4">
            <div>
              <label className="mb-4 block text-sm font-medium">Plan</label>
              <div className="flex gap-2.5">
                {([
                  { value: "gratuit", label: "Gratuit", icon: UserIcon },
                  { value: "invite", label: "Invité", icon: Gift },
                  { value: "vip", label: "VIP", icon: Crown },
                ] as const).map((p) => {
                  const isActive = selectedPlan === p.value;
                  const Icon = p.icon;
                  return (
                    <button
                      key={p.value}
                      type="button"
                      onClick={() => setSelectedPlan(p.value)}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                        isActive
                          ? "border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]"
                          : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                      }`}
                    >
                      <Icon className="size-3.5" />
                      {p.label}
                    </button>
                  );
                })}
              </div>
            </div>
            {selectedPlan === "invite" && (
              <div>
                <label className="mb-4 block text-sm font-medium">Durée</label>
                <div className="flex gap-2.5">
                  {["1", "2", "3"].map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setSelectedDuration(d)}
                      className={`rounded-full border px-4 py-2 text-sm font-medium transition-colors ${
                        selectedDuration === d
                          ? "border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]"
                          : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                      }`}
                    >
                      {d} mois
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPlanDialogOpen(false)}>
              Annuler
            </Button>
            <Button onClick={handlePlanSubmit} disabled={planSaving}>
              {planSaving ? "Enregistrement..." : "Enregistrer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer l&apos;utilisateur</DialogTitle>
            <DialogDescription>
              Êtes-vous sûr de vouloir supprimer <strong>{userToDelete?.full_name}</strong> ({userToDelete?.email}) ?
              Cette action est irréversible. Toutes ses données (conversations, memberships, compte) seront supprimées.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Suppression..." : "Supprimer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
