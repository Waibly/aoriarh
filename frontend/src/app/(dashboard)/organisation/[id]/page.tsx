"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import Link from "next/link";
import {
  ArrowLeft,
  Pencil,
  Trash2,
  UserMinus,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import type { Membership, Organisation } from "@/types/api";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { OrgFormDialog } from "@/components/org-form-dialog";

type AccountMember = {
  id: string;
  user_id: string;
  user_email: string;
  user_full_name: string | null;
  role_in_org: "manager" | "user";
  access_all: boolean;
};

export default function OrganisationDetailPage() {
  const params = useParams<{ id: string }>();
  const orgId = params.id;
  const { data: session } = useSession();
  const token = session?.access_token;
  const router = useRouter();
  const { refetchOrgs, setCurrentOrgId } = useOrg();

  const [org, setOrg] = useState<Organisation | null>(null);
  const [loadingOrg, setLoadingOrg] = useState(true);
  const [members, setMembers] = useState<Membership[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [accountMembers, setAccountMembers] = useState<AccountMember[]>([]);
  const [isOrgManager, setIsOrgManager] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<Membership | null>(null);

  const fetchOrg = useCallback(async () => {
    if (!orgId || !token) return;
    setLoadingOrg(true);
    try {
      const o = await apiFetch<Organisation>(`/organisations/${orgId}`, { token });
      setOrg(o);
    } catch {
      toast.error("Organisation introuvable");
      router.push("/organisation");
    } finally {
      setLoadingOrg(false);
    }
  }, [orgId, token, router]);

  const fetchMembers = useCallback(async () => {
    if (!orgId || !token) return;
    setLoadingMembers(true);
    try {
      const data = await apiFetch<Membership[]>(
        `/organisations/${orgId}/members`,
        { token },
      );
      setMembers(data);
      const myMembership = data.find((m) => m.user_id === session?.user?.id);
      setIsOrgManager(
        session?.user?.role === "admin" ||
          myMembership?.role_in_org === "manager",
      );
    } catch {
      setMembers([]);
    } finally {
      setLoadingMembers(false);
    }
  }, [orgId, token, session?.user?.id, session?.user?.role]);

  const fetchAccountMembers = useCallback(async () => {
    if (!token) return;
    try {
      const data = await apiFetch<AccountMember[]>("/team/members", { token });
      setAccountMembers(data);
    } catch {
      setAccountMembers([]);
    }
  }, [token]);

  useEffect(() => {
    fetchOrg();
    fetchMembers();
    fetchAccountMembers();
  }, [fetchOrg, fetchMembers, fetchAccountMembers]);

  const handleMemberRoleChange = async (
    membershipId: string,
    newRole: "manager" | "user",
  ) => {
    if (!token) return;
    try {
      await apiFetch(`/organisations/${orgId}/members/${membershipId}`, {
        method: "PATCH",
        token,
        body: JSON.stringify({ role_in_org: newRole }),
      });
      toast.success("Rôle mis à jour");
      await fetchMembers();
    } catch (err) {
      toast.error(
        err instanceof Error && err.message
          ? err.message
          : "Impossible de modifier le rôle",
      );
    }
  };

  const handleRemoveMember = async () => {
    if (!token || !removeTarget) return;
    try {
      await apiFetch(`/organisations/${orgId}/members/${removeTarget.id}`, {
        method: "DELETE",
        token,
      });
      toast.success("Membre retiré de cette organisation");
      setRemoveTarget(null);
      await fetchMembers();
    } catch (err) {
      toast.error(
        err instanceof Error && err.message
          ? err.message
          : "Impossible de retirer ce membre",
      );
    }
  };

  const handleOrgDeleted = useCallback(async () => {
    await refetchOrgs();
    router.push("/organisation");
  }, [refetchOrgs, router]);

  const handleOpenInChat = () => {
    if (org) {
      setCurrentOrgId(org.id);
      router.push("/chat");
    }
  };

  if (loadingOrg) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!org) return null;

  const existingUserIds = new Set(members.map((m) => m.user_id));
  const availableToAdd = accountMembers.filter(
    (am) => !existingUserIds.has(am.user_id),
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/organisation">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Toutes les organisations
          </Link>
        </Button>
      </div>

      {/* Org info */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle className="text-2xl">{org.name}</CardTitle>
            <CardDescription>
              Créée le {new Date(org.created_at).toLocaleDateString("fr-FR")}
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleOpenInChat}>
              Ouvrir dans le chat
            </Button>
            {isOrgManager && (
              <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
                <Pencil className="mr-2 h-4 w-4" />
                Modifier
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm text-muted-foreground">Forme juridique</p>
            <p className="font-medium">{org.forme_juridique ?? "Non renseignée"}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Effectif</p>
            <p className="font-medium">
              {org.taille ? `${org.taille} salariés` : "Non renseigné"}
            </p>
          </div>
          <div className="col-span-2">
            <p className="text-sm text-muted-foreground">Secteur d&apos;activité</p>
            <p className="font-medium">{org.secteur_activite ?? "Non renseigné"}</p>
          </div>
        </CardContent>
      </Card>

      {/* Members */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>Membres de cette organisation</CardTitle>
            <CardDescription>
              {members.length} membre{members.length > 1 ? "s" : ""} avec accès à {org.name}
            </CardDescription>
          </div>
          {isOrgManager && (
            <Button
              size="sm"
              onClick={() => setAddMemberOpen(true)}
              disabled={availableToAdd.length === 0}
              title={
                availableToAdd.length === 0
                  ? "Tous les membres du compte sont déjà dans cette organisation. Invitez d'abord un nouveau collaborateur depuis l'onglet Équipe."
                  : ""
              }
            >
              <UserPlus className="mr-2 h-4 w-4" />
              Ajouter un membre
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {loadingMembers ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : members.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Aucun membre n&apos;a encore accès à cette organisation.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nom</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead className="w-[180px]">Rôle dans cette organisation</TableHead>
                  <TableHead className="text-right w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => {
                  const isMe = member.user_id === session?.user?.id;
                  return (
                    <TableRow key={member.id}>
                      <TableCell className="font-medium">
                        {member.user_full_name ?? "—"}
                        {isMe && (
                          <span className="ml-2 text-xs text-muted-foreground">(vous)</span>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {member.user_email}
                      </TableCell>
                      <TableCell>
                        {isOrgManager && !isMe ? (
                          <Select
                            value={member.role_in_org}
                            onValueChange={(v) =>
                              handleMemberRoleChange(member.id, v as "manager" | "user")
                            }
                          >
                            <SelectTrigger className="h-8">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="user">Utilisateur</SelectItem>
                              <SelectItem value="manager">Manager</SelectItem>
                            </SelectContent>
                          </Select>
                        ) : (
                          <Badge
                            variant="outline"
                            className={
                              member.role_in_org === "manager"
                                ? "rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0]"
                                : "rounded-full"
                            }
                          >
                            {member.role_in_org === "manager" ? "Manager" : "Utilisateur"}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {isOrgManager && !isMe && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={() => setRemoveTarget(member)}
                            title="Retirer de cette organisation"
                          >
                            <UserMinus className="h-4 w-4" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {isOrgManager && (
            <p className="text-xs text-muted-foreground mt-3">
              Retirer un membre lui fait perdre l&apos;accès à cette organisation uniquement.
              Son compte reste actif — utilisez l&apos;onglet{" "}
              <Link href="/team" className="underline hover:text-foreground">
                Équipe
              </Link>{" "}
              pour le supprimer complètement.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Danger zone */}
      {isOrgManager && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-destructive">Zone de danger</CardTitle>
            <CardDescription>
              La suppression de l&apos;organisation est irréversible. Toutes les
              données associées (documents, conversations, membres) seront
              définitivement supprimées.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="mr-2 h-4 w-4" />
              Supprimer l&apos;organisation
            </Button>
          </CardContent>
        </Card>
      )}

      {isOrgManager && token && (
        <>
          <OrgFormDialog
            open={editOpen}
            onOpenChange={setEditOpen}
            org={org}
            onSubmit={async (data) => {
              await apiFetch(`/organisations/${org.id}`, {
                method: "PATCH",
                token,
                body: JSON.stringify(data),
              });
              await Promise.all([fetchOrg(), refetchOrgs()]);
            }}
          />
          <AddMemberDialog
            open={addMemberOpen}
            onOpenChange={setAddMemberOpen}
            orgId={org.id}
            orgName={org.name}
            token={token}
            candidates={availableToAdd}
            onAdded={fetchMembers}
          />
          <DeleteOrgDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            org={org}
            token={token}
            onDeleted={handleOrgDeleted}
          />
        </>
      )}

      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Retirer de cette organisation</DialogTitle>
            <DialogDescription>
              Retirer{" "}
              <strong>
                {removeTarget?.user_full_name || removeTarget?.user_email}
              </strong>{" "}
              de l&apos;organisation « {org.name} » ? Cette personne n&apos;aura plus accès
              aux documents et conversations de cette organisation. Son compte reste actif.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoveTarget(null)}>
              Annuler
            </Button>
            <Button variant="destructive" onClick={handleRemoveMember}>
              Retirer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AddMemberDialog({
  open,
  onOpenChange,
  orgId,
  orgName,
  token,
  candidates,
  onAdded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  orgName: string;
  token: string;
  candidates: AccountMember[];
  onAdded: () => Promise<void>;
}) {
  const [selectedEmail, setSelectedEmail] = useState("");
  const [role, setRole] = useState<"manager" | "user">("user");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setSelectedEmail("");
      setRole("user");
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedEmail) return;
    setSubmitting(true);
    try {
      await apiFetch(`/organisations/${orgId}/members`, {
        method: "POST",
        token,
        body: JSON.stringify({ email: selectedEmail, role_in_org: role }),
      });
      toast.success("Membre ajouté à cette organisation");
      onOpenChange(false);
      await onAdded();
    } catch (err) {
      toast.error(
        err instanceof Error && err.message
          ? err.message
          : "Impossible d'ajouter ce membre",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Ajouter un membre à « {orgName} »</DialogTitle>
          <DialogDescription>
            Choisissez un collaborateur déjà présent dans votre équipe.
            Pour inviter une nouvelle personne, passez d&apos;abord par l&apos;onglet{" "}
            <Link href="/team" className="underline hover:text-foreground">
              Équipe
            </Link>
            .
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="member-email">Collaborateur</Label>
            <Select value={selectedEmail} onValueChange={setSelectedEmail}>
              <SelectTrigger id="member-email">
                <SelectValue placeholder="Choisir dans votre équipe..." />
              </SelectTrigger>
              <SelectContent>
                {candidates.length === 0 ? (
                  <div className="px-2 py-1.5 text-sm text-muted-foreground">
                    Tous les membres du compte sont déjà dans cette organisation.
                  </div>
                ) : (
                  candidates.map((c) => (
                    <SelectItem key={c.user_id} value={c.user_email}>
                      {c.user_full_name ?? c.user_email}
                      <span className="text-xs text-muted-foreground ml-2">
                        {c.user_email}
                      </span>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="member-role">Rôle dans cette organisation</Label>
            <Select value={role} onValueChange={(v) => setRole(v as "manager" | "user")}>
              <SelectTrigger id="member-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">Utilisateur (consulter, poser des questions)</SelectItem>
                <SelectItem value="manager">Manager (gérer docs, membres, paramètres)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Annuler
            </Button>
            <Button type="submit" disabled={!selectedEmail || submitting}>
              {submitting ? "Ajout..." : "Ajouter"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteOrgDialog({
  open,
  onOpenChange,
  org,
  token,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  org: { id: string; name: string };
  token: string;
  onDeleted: () => Promise<void>;
}) {
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) setConfirmation("");
  }, [open]);

  const matches = confirmation === org.name;

  async function handleDelete() {
    setSubmitting(true);
    try {
      await apiFetch(`/organisations/${org.id}`, {
        method: "DELETE",
        token,
      });
      toast.success("Organisation supprimée");
      onOpenChange(false);
      await onDeleted();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Impossible de supprimer l'organisation",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Supprimer l&apos;organisation</DialogTitle>
          <DialogDescription>
            Cette action est irréversible. Toutes les données seront
            définitivement supprimées. Pour confirmer, tapez le nom de
            l&apos;organisation : <strong>{org.name}</strong>
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="delete-confirm">Nom de l&apos;organisation</Label>
            <Input
              id="delete-confirm"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              placeholder={org.name}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Annuler
            </Button>
            <Button
              variant="destructive"
              disabled={!matches || submitting}
              onClick={handleDelete}
            >
              {submitting ? "Suppression..." : "Supprimer l'organisation"}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

