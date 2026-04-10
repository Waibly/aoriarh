"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Crown,
  Mail,
  Search,
  Trash2,
  Users,
  FileText,
  MessageSquare,
  UserCheck,
  Gift,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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

const PLAN_CONFIG = {
  gratuit: { label: "Gratuit", className: "rounded-full", icon: UserCheck },
  invite: { label: "Invité", className: "rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]", icon: Gift },
  vip: { label: "VIP", className: "rounded-full border-amber-500 bg-amber-500/10 text-amber-600", icon: Crown },
} as const;

export default function WorkspacesPage() {
  const { data: session } = useSession();
  const token = session?.access_token;

  const [data, setData] = useState<WorkspacesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<{ user_id: string; email: string } | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const handleDeleteUser = async () => {
    if (!deleteTarget || !token) return;
    setDeleteLoading(true);
    try {
      await apiFetch(`/admin/users/${deleteTarget.user_id}`, {
        method: "DELETE",
        token,
      });
      toast.success(`Utilisateur ${deleteTarget.email} supprimé`);
      setDeleteTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de supprimer cet utilisateur");
    } finally {
      setDeleteLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchData = useCallback(async () => {
    if (!token) return;
    try {
      const params = debouncedSearch ? `?search=${encodeURIComponent(debouncedSearch)}` : "";
      const res = await apiFetch<WorkspacesResponse>(
        `/admin/workspaces/${params}`,
        { token },
      );
      setData(res);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur lors du chargement");
    } finally {
      setLoading(false);
    }
  }, [token, debouncedSearch]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Clients et espaces de travail
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Vue d&apos;ensemble de tous les comptes, organisations et membres.
        </p>
      </div>

      {/* Totals */}
      {data && (
        <div className="grid grid-cols-4 gap-4">
          <StatCard icon={Users} label="Utilisateurs" value={data.totals.users} />
          <StatCard icon={Building2} label="Espaces de travail" value={data.totals.workspaces} />
          <StatCard icon={Building2} label="Organisations" value={data.totals.organisations} />
          <StatCard icon={FileText} label="Documents (orgs)" value={data.totals.documents} />
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

      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-40 w-full" />)}
        </div>
      ) : !data || data.workspaces.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">
          {debouncedSearch ? "Aucun résultat pour cette recherche." : "Aucun espace de travail."}
        </p>
      ) : (
        <div className="space-y-4">
          {data.workspaces.map((ws) => (
            <WorkspaceCard
              key={ws.account_id}
              workspace={ws}
              token={token!}
              onUpdated={fetchData}
              onDeleteUser={(user_id, email) => setDeleteTarget({ user_id, email })}
            />
          ))}

          {data.orphan_users.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Utilisateurs sans espace</CardTitle>
                <CardDescription>
                  {data.orphan_users.length} utilisateur{data.orphan_users.length > 1 ? "s" : ""} sans espace de travail
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {data.orphan_users.map((u) => (
                    <div key={u.user_id} className="flex items-center gap-3 text-sm">
                      <Mail className="h-4 w-4 text-muted-foreground" />
                      <span>{u.email}</span>
                      <span className="text-muted-foreground">({u.full_name})</span>
                      <Badge variant="outline" className="rounded-full text-xs">{u.role}</Badge>
                      {u.role !== "admin" && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 ml-auto"
                          onClick={() => setDeleteTarget({ user_id: u.user_id, email: u.email })}
                          title="Supprimer"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Delete confirmation dialog */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Supprimer l&apos;utilisateur</DialogTitle>
            <DialogDescription>
              Voulez-vous vraiment supprimer{" "}
              <strong>{deleteTarget?.email}</strong> ? Ses conversations et
              messages seront supprimés. Les documents et organisations ne
              sont pas impactés.
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
    </div>
  );
}

function StatCard({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number }) {
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

function WorkspaceCard({
  workspace: ws,
  token,
  onUpdated,
  onDeleteUser,
}: {
  workspace: WorkspaceOverview;
  token: string;
  onUpdated: () => void;
  onDeleteUser: (user_id: string, email: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [planSaving, setPlanSaving] = useState(false);
  const [pendingPlan, setPendingPlan] = useState<string | null>(null);
  const [pendingDuration, setPendingDuration] = useState("3");

  const planConfig = PLAN_CONFIG[ws.plan as keyof typeof PLAN_CONFIG] ?? PLAN_CONFIG.gratuit;

  const handlePlanConfirm = async () => {
    if (!pendingPlan) return;
    setPlanSaving(true);
    try {
      await apiFetch(`/admin/users/accounts/${ws.account_id}/plan`, {
        method: "PUT",
        token,
        body: JSON.stringify({
          plan: pendingPlan,
          duration_months: pendingPlan === "invite" ? Number(pendingDuration) : null,
        }),
      });
      toast.success(`Plan mis à jour : ${pendingPlan}`);
      setPendingPlan(null);
      onUpdated();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Erreur");
    } finally {
      setPlanSaving(false);
    }
  };

  return (
    <Card>
      {/* Compact header: name + plan on one line */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2 min-w-0">
          <Building2 className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="font-semibold truncate">{ws.name}</span>
          <Badge variant="outline" className={`${planConfig.className} text-xs shrink-0`}>
            {planConfig.label}
          </Badge>
          {ws.plan === "invite" && ws.plan_expires_at && (
            <span className="text-xs text-muted-foreground shrink-0">
              exp. {new Date(ws.plan_expires_at).toLocaleDateString("fr-FR")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
          <span>{ws.organisations.length} org{ws.organisations.length > 1 ? "s" : ""}</span>
          <span>{ws.members.length} membre{ws.members.length > 1 ? "s" : ""}</span>
          <span>{ws.total_documents} docs</span>
          <span>{ws.total_questions} questions</span>
        </div>
      </div>

      {/* Owner info + plan change */}
      <div className="flex items-center justify-between px-4 py-2 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Mail className="h-3.5 w-3.5" />
          <a href={`mailto:${ws.owner_email}`} className="hover:text-primary hover:underline">
            {ws.owner_email}
          </a>
          <span>— {ws.owner_name}</span>
          {ws.created_at && (
            <span className="text-xs">
              — inscrit le {new Date(ws.created_at).toLocaleDateString("fr-FR")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {pendingPlan ? (
            <>
              {pendingPlan === "invite" && (
                <Select value={pendingDuration} onValueChange={setPendingDuration}>
                  <SelectTrigger className="h-7 w-[90px] text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 mois</SelectItem>
                    <SelectItem value="2">2 mois</SelectItem>
                    <SelectItem value="3">3 mois</SelectItem>
                  </SelectContent>
                </Select>
              )}
              <Button size="sm" variant="default" className="h-7 text-xs" onClick={handlePlanConfirm} disabled={planSaving}>
                {planSaving ? "..." : `Passer en ${pendingPlan}`}
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setPendingPlan(null)}>
                Annuler
              </Button>
            </>
          ) : (
            <Select value="" onValueChange={(v) => setPendingPlan(v)}>
              <SelectTrigger className="h-7 w-[130px] text-xs">
                <SelectValue placeholder="Changer le plan" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="gratuit">Gratuit</SelectItem>
                <SelectItem value="invite">Invité</SelectItem>
                <SelectItem value="vip">VIP</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      {/* Expandable details */}
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <CollapsibleTrigger asChild>
          <button className="flex w-full items-center gap-1 border-t px-4 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted/50 transition-colors">
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Détails
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 pb-3 space-y-3">
            {/* Organisations */}
            {ws.organisations.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-muted-foreground mb-1">Organisations</p>
                <div className="space-y-1 pl-4">
                  {ws.organisations.map((org) => (
                    <div key={org.id} className="flex items-center gap-2 text-sm">
                      <span className="font-medium">{org.name}</span>
                      <span className="text-xs text-muted-foreground">
                        — {org.documents_count} docs, {org.members_count} membres
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Members */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-1">Membres</p>
              <div className="space-y-1 pl-4">
                {ws.members.map((m) => (
                  <div key={m.user_id} className="flex items-center gap-2 text-sm">
                    <a href={`mailto:${m.email}`} className="hover:text-primary hover:underline">
                      {m.email}
                    </a>
                    <span className="text-muted-foreground text-xs">({m.full_name})</span>
                    {m.is_owner ? (
                      <Badge variant="outline" className="rounded-full border-amber-500 bg-amber-500/10 text-amber-600 text-[10px] px-1.5 py-0">
                        Propriétaire
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="rounded-full text-[10px] px-1.5 py-0">
                        {m.role_in_workspace === "manager" ? "Manager" : "Utilisateur"}
                      </Badge>
                    )}
                    {!m.is_owner && m.role !== "admin" && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 ml-auto"
                        onClick={() => onDeleteUser(m.user_id, m.email)}
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
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
