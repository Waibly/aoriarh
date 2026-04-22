"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Plus,
  Trash2,
  RotateCw,
  X,
  Pencil,
  Globe,
  Building2,
  Crown,
  Info,
} from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import type { AccountMember, Invitation, Organisation } from "@/types/api";
import {
  fetchUsageSummary,
  fetchAddons,
  fetchQuota,
  type UsageSummary,
  type ActiveAddon,
  type QuotaInfo,
} from "@/lib/billing-api";
import { LimitReachedDialog } from "@/components/limit-reached-dialog";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useOrg } from "@/lib/org-context";

export default function TeamPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const { workspaceName } = useOrg();

  const [members, setMembers] = useState<AccountMember[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [organisations, setOrganisations] = useState<Organisation[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AccountMember | null>(null);
  const [removeTarget, setRemoveTarget] = useState<AccountMember | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [addons, setAddons] = useState<ActiveAddon[]>([]);
  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [limitOpen, setLimitOpen] = useState(false);

  const fetchBillingState = useCallback(async () => {
    if (!token) return;
    try {
      const [u, a, q] = await Promise.all([
        fetchUsageSummary(token),
        fetchAddons(token),
        fetchQuota(token),
      ]);
      setUsage(u);
      setAddons(a);
      setQuota(q);
    } catch {
      // Silencieux — backend garde-fou.
    }
  }, [token]);

  useEffect(() => {
    fetchBillingState();
    const handler = () => fetchBillingState();
    window.addEventListener("quota-updated", handler);
    return () => window.removeEventListener("quota-updated", handler);
  }, [fetchBillingState]);

  const fetchMembers = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<AccountMember[]>("/team/members", { token });
      setMembers(data);
    } catch {
      setMembers([]);
    }
  }, [token]);

  const fetchInvitations = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<Invitation[]>("/team/invitations", { token });
      setInvitations(data.filter((inv) => inv.status === "pending"));
    } catch {
      setInvitations([]);
    }
  }, [token]);

  const fetchOrganisations = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<Organisation[]>("/team/organisations", { token });
      setOrganisations(data);
    } catch {
      setOrganisations([]);
    }
  }, [token]);

  useEffect(() => {
    Promise.all([fetchMembers(), fetchInvitations(), fetchOrganisations()]).finally(
      () => setLoading(false)
    );
  }, [fetchMembers, fetchInvitations, fetchOrganisations]);

  const handleRemoveConfirm = async () => {
    if (!removeTarget || !token) return;
    try {
      await apiFetch(`/team/members/${removeTarget.id}`, {
        method: "DELETE",
        token,
      });
      toast.success("Membre retiré de l'équipe");
      fetchMembers();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de retirer ce membre");
    }
    setRemoveTarget(null);
  };

  if (!session?.user || (session.user.role !== "manager" && session.user.role !== "admin")) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Équipe</h1>
        <p className="text-muted-foreground">
          Seuls les managers peuvent accéder à cette page.
        </p>
      </div>
    );
  }

  const ownerName = session.user.full_name ?? "Propriétaire";
  const ownerEmail = session.user.email ?? "";
  const ownerInitials = ownerName
    .split(" ")
    .map((n: string) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Équipe{workspaceName ? ` — ${workspaceName}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Gérez les membres de votre espace de travail et leurs accès aux organisations.
        </p>
      </div>

      {/* Owner card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Propriétaire de l&apos;espace de travail</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-4">
            <Avatar className="h-12 w-12">
              <AvatarFallback className="bg-primary/10 text-primary text-sm font-semibold">
                {ownerInitials}
              </AvatarFallback>
            </Avatar>
            <div className="flex-1 min-w-0">
              <p className="font-medium">{ownerName}</p>
              <p className="text-sm text-muted-foreground truncate">{ownerEmail}</p>
            </div>
            <Badge
              variant="outline"
              className="rounded-full border-amber-500 bg-amber-500/10 text-amber-600"
            >
              <Crown className="mr-1 h-3 w-3" />
              Propriétaire
            </Badge>
            <Badge
              variant="outline"
              className="rounded-full border-teal-600 bg-teal-600/10 text-teal-600"
            >
              <Globe className="mr-1 h-3 w-3" />
              Toutes les orgs
            </Badge>
          </div>
        </CardContent>
      </Card>

      {/* Team members */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>Collaborateurs</CardTitle>
            <CardDescription>
              {(() => {
                const used = usage?.users.used ?? members.length + 1;
                const limit = usage?.users.limit ?? 0;
                const pct = limit > 0 ? used / limit : 0;
                return (
                  <>
                    <strong>{used}</strong>
                    {limit > 0 && (
                      <> / {limit} utilisateur{limit > 1 ? "s" : ""} inclus</>
                    )}
                    {pct >= 0.8 && pct < 1 && (
                      <span className="ml-2 inline-block rounded-full bg-orange-500/10 text-orange-600 dark:text-orange-400 px-2 py-0.5 text-xs font-medium">
                        Proche de la limite
                      </span>
                    )}
                  </>
                );
              })()}
            </CardDescription>
          </div>
          <Button
            size="sm"
            onClick={() => {
              const used = usage?.users.used ?? members.length + 1;
              const limit = usage?.users.limit ?? 0;
              if (limit > 0 && used >= limit) {
                setLimitOpen(true);
              } else {
                setInviteOpen(true);
              }
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Inviter
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : members.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              Aucun collaborateur. Invitez votre premier membre d&apos;équipe.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nom</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Rôle</TableHead>
                  <TableHead>Accès</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => (
                  <TableRow key={member.id}>
                    <TableCell className="font-medium">
                      {member.user_full_name ?? "—"}
                    </TableCell>
                    <TableCell>{member.user_email}</TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={
                          member.role_in_org === "manager"
                            ? "rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0]"
                            : "rounded-full"
                        }
                      >
                        {member.role_in_org === "manager"
                          ? "Manager"
                          : "Utilisateur"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {member.access_all ? (
                        <Badge
                          variant="outline"
                          className="rounded-full border-teal-600 bg-teal-600/10 text-teal-600"
                        >
                          <Globe className="mr-1 h-3 w-3" />
                          Toutes les orgs
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="rounded-full"
                        >
                          <Building2 className="mr-1 h-3 w-3" />
                          {member.organisation_names.length} org
                          {member.organisation_names.length > 1 ? "s" : ""}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setEditTarget(member)}
                          title="Modifier l'accès"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setRemoveTarget(member)}
                          title="Retirer"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pending invitations */}
      {invitations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Invitations en attente</CardTitle>
            <CardDescription>
              {invitations.length} invitation{invitations.length > 1 ? "s" : ""}{" "}
              en attente
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Rôle</TableHead>
                  <TableHead>Accès</TableHead>
                  <TableHead>Envoyé le</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.map((inv) => (
                  <InvitationRow
                    key={inv.id}
                    invitation={inv}
                    token={token!}
                    onUpdated={fetchInvitations}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Invite dialog */}
      <InviteTeamDialog
        open={inviteOpen}
        onOpenChange={(open) => {
          setInviteOpen(open);
          if (open) fetchOrganisations();
        }}
        token={token!}
        organisations={organisations}
        onInvited={() => {
          fetchInvitations();
        }}
      />

      {/* Edit dialog */}
      {editTarget && (
        <EditMemberDialog
          open={!!editTarget}
          onOpenChange={(open) => {
            if (!open) setEditTarget(null);
          }}
          member={editTarget}
          token={token!}
          organisations={organisations}
          onUpdated={fetchMembers}
        />
      )}

      {/* Remove confirmation */}
      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Retirer le membre</DialogTitle>
            <DialogDescription>
              Voulez-vous vraiment retirer{" "}
              <strong>
                {removeTarget?.user_full_name || removeTarget?.user_email}
              </strong>{" "}
              de l&apos;équipe ? Cette personne perdra l&apos;accès à toutes les
              organisations.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleRemoveConfirm}>
              Retirer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <LimitReachedDialog
        open={limitOpen}
        onOpenChange={setLimitOpen}
        resource="user"
        currentPlan={quota?.plan ?? "gratuit"}
        includedCount={usage?.users.limit ?? 0}
        usedCount={usage?.users.used ?? 0}
        activeAddonCount={addons
          .filter((a) => a.addon_type === "extra_user")
          .reduce((sum, a) => sum + a.quantity, 0)}
        addonCap={3}
      />
    </div>
  );
}

// --- InviteTeamDialog ---

function InviteTeamDialog({
  open,
  onOpenChange,
  token,
  organisations,
  onInvited,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token: string;
  organisations: Organisation[];
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"user" | "manager">("user");
  const [accessAll, setAccessAll] = useState(true);
  const [selectedOrgIds, setSelectedOrgIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setEmail("");
      setRole("user");
      setAccessAll(true);
      setSelectedOrgIds([]);
      setError(null);
    }
  }, [open]);

  function toggleOrg(orgId: string) {
    setSelectedOrgIds((prev) =>
      prev.includes(orgId) ? prev.filter((id) => id !== orgId) : [...prev, orgId]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/team/invite", {
        method: "POST",
        token,
        body: JSON.stringify({
          email,
          role_in_org: role,
          access_all: accessAll,
          ...(!accessAll && selectedOrgIds.length > 0
            ? { organisation_ids: selectedOrgIds }
            : {}),
        }),
      });
      toast.success("Invitation envoyée");
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("quota-updated"));
      }
      onInvited();
      onOpenChange(false);
    } catch (err) {
      setError(
        err instanceof Error && err.message
          ? err.message
          : "L'invitation n'a pas pu être envoyée. Réessayez ou contactez le support.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Inviter un membre</DialogTitle>
          <DialogDescription>
            Un email d&apos;invitation sera envoyé pour rejoindre votre espace
            de travail. Le membre aura accès aux organisations sélectionnées.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="team-invite-email">Email *</Label>
            <Input
              id="team-invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@exemple.fr"
              required
            />
          </div>

          {/* Role toggle */}
          <div className="space-y-2">
            <Label>Rôle</Label>
            <div className="flex gap-1 rounded-lg border p-1">
              <button
                type="button"
                onClick={() => setRole("user")}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Utilisateur
              </button>
              <button
                type="button"
                onClick={() => setRole("manager")}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  role === "manager"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Manager
              </button>
            </div>
            <div className="flex items-start gap-1.5 rounded-md bg-muted/50 p-2">
              <Info className="h-3.5 w-3.5 text-muted-foreground mt-0.5 shrink-0" />
              <p className="text-xs text-muted-foreground">
                <strong>Utilisateur</strong> : peut consulter le chat et les documents.{" "}
                <strong>Manager</strong> : peut aussi ajouter des documents, gérer les membres et créer des organisations.
              </p>
            </div>
          </div>

          {/* Access toggle */}
          <div className="space-y-2">
            <Label>Accès</Label>
            <div className="flex gap-1 rounded-lg border p-1">
              <button
                type="button"
                onClick={() => setAccessAll(true)}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  accessAll
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Toutes les organisations
              </button>
              <button
                type="button"
                onClick={() => setAccessAll(false)}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  !accessAll
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Spécifiques
              </button>
            </div>
          </div>

          {/* Org selection */}
          {!accessAll && (
            <div className="space-y-2">
              <Label>Organisations</Label>
              {organisations.length === 0 ? (
                <p className="py-3 text-center text-sm text-muted-foreground">
                  Aucune organisation disponible.
                </p>
              ) : (
                <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
                  {organisations.map((org) => (
                    <button
                      key={org.id}
                      type="button"
                      onClick={() => toggleOrg(org.id)}
                      className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                        selectedOrgIds.includes(org.id)
                          ? "bg-primary/10 text-primary font-medium"
                          : "hover:bg-muted"
                      }`}
                    >
                      <div
                        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                          selectedOrgIds.includes(org.id)
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-muted-foreground/30"
                        }`}
                      >
                        {selectedOrgIds.includes(org.id) && (
                          <svg
                            className="h-3 w-3"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={3}
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              d="M5 13l4 4L19 7"
                            />
                          </svg>
                        )}
                      </div>
                      {org.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="submit"
              disabled={
                submitting ||
                !email.trim() ||
                (!accessAll && selectedOrgIds.length === 0)
              }
            >
              {submitting ? "Invitation..." : "Inviter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- EditMemberDialog ---

function EditMemberDialog({
  open,
  onOpenChange,
  member,
  token,
  organisations,
  onUpdated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  member: AccountMember;
  token: string;
  organisations: Organisation[];
  onUpdated: () => void;
}) {
  const [role, setRole] = useState<"user" | "manager">(member.role_in_org);
  const [accessAll, setAccessAll] = useState(member.access_all);
  const [selectedOrgIds, setSelectedOrgIds] = useState<string[]>(() => {
    if (member.access_all) return organisations.map((o) => o.id);
    return organisations
      .filter((o) => member.organisation_names.includes(o.name))
      .map((o) => o.id);
  });
  const [submitting, setSubmitting] = useState(false);

  function toggleOrg(orgId: string) {
    setSelectedOrgIds((prev) =>
      prev.includes(orgId) ? prev.filter((id) => id !== orgId) : [...prev, orgId]
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch(`/team/members/${member.id}`, {
        method: "PATCH",
        token,
        body: JSON.stringify({
          role_in_org: role,
          access_all: accessAll,
          ...(!accessAll ? { organisation_ids: selectedOrgIds } : {}),
        }),
      });
      toast.success("Membre mis à jour");
      onUpdated();
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Impossible de mettre à jour ce membre");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modifier l&apos;accès</DialogTitle>
          <DialogDescription>
            {member.user_full_name || member.user_email}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Role toggle */}
          <div className="space-y-2">
            <Label>Rôle</Label>
            <div className="flex gap-1 rounded-lg border p-1">
              <button
                type="button"
                onClick={() => setRole("user")}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Utilisateur
              </button>
              <button
                type="button"
                onClick={() => setRole("manager")}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  role === "manager"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Manager
              </button>
            </div>
          </div>

          {/* Access toggle */}
          <div className="space-y-2">
            <Label>Accès</Label>
            <div className="flex gap-1 rounded-lg border p-1">
              <button
                type="button"
                onClick={() => setAccessAll(true)}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  accessAll
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Toutes les organisations
              </button>
              <button
                type="button"
                onClick={() => setAccessAll(false)}
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  !accessAll
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
              >
                Spécifiques
              </button>
            </div>
          </div>

          {!accessAll && (
            <div className="space-y-2">
              <Label>Organisations</Label>
              <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
                {organisations.map((org) => (
                  <button
                    key={org.id}
                    type="button"
                    onClick={() => toggleOrg(org.id)}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      selectedOrgIds.includes(org.id)
                        ? "bg-primary/10 text-primary font-medium"
                        : "hover:bg-muted"
                    }`}
                  >
                    <div
                      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                        selectedOrgIds.includes(org.id)
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-muted-foreground/30"
                      }`}
                    >
                      {selectedOrgIds.includes(org.id) && (
                        <svg
                          className="h-3 w-3"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={3}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M5 13l4 4L19 7"
                          />
                        </svg>
                      )}
                    </div>
                    {org.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || (!accessAll && selectedOrgIds.length === 0)}
            >
              {submitting ? "Enregistrement..." : "Enregistrer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- InvitationRow ---

function InvitationRow({
  invitation,
  token,
  onUpdated,
}: {
  invitation: Invitation;
  token: string;
  onUpdated: () => void;
}) {
  const [resending, setResending] = useState(false);

  async function handleResend() {
    setResending(true);
    try {
      await apiFetch(`/team/invitations/${invitation.id}/resend`, {
        method: "POST",
        token,
      });
      toast.success("Invitation renvoyée");
      onUpdated();
    } finally {
      setResending(false);
    }
  }

  async function handleCancel() {
    await apiFetch(`/team/invitations/${invitation.id}`, {
      method: "DELETE",
      token,
    });
    toast.success("Invitation annulée");
    onUpdated();
  }

  return (
    <TableRow>
      <TableCell>{invitation.email}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={
            invitation.role_in_org === "manager"
              ? "rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0]"
              : "rounded-full"
          }
        >
          {invitation.role_in_org === "manager" ? "Manager" : "Utilisateur"}
        </Badge>
      </TableCell>
      <TableCell>
        {invitation.access_all ? (
          <Badge
            variant="outline"
            className="rounded-full border-teal-600 bg-teal-600/10 text-teal-600"
          >
            Toutes les orgs
          </Badge>
        ) : (
          <Badge variant="outline" className="rounded-full">
            Orgs spécifiques
          </Badge>
        )}
      </TableCell>
      <TableCell>
        {new Date(invitation.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={handleResend}
            disabled={resending}
            title="Renvoyer l'invitation"
          >
            <RotateCw
              className={`h-4 w-4 ${resending ? "animate-spin" : ""}`}
            />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleCancel}
            title="Annuler l'invitation"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}
