"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Pencil, Plus, Trash2, UserCog, RotateCw, X } from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import type { Invitation, Membership } from "@/types/api";
import { FORME_JURIDIQUE_OPTIONS, TAILLE_OPTIONS } from "@/types/api";
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

export default function OrganisationPage() {
  const { data: session } = useSession();
  const { currentOrg, refetchOrgs } = useOrg();
  const token = session?.access_token;
  const router = useRouter();

  const [members, setMembers] = useState<Membership[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isOrgManager, setIsOrgManager] = useState(false);

  const handleOrgDeleted = useCallback(async () => {
    await refetchOrgs();
    router.push("/chat");
  }, [refetchOrgs, router]);

  const fetchInvitations = useCallback(async () => {
    if (!currentOrg || !token) return;
    try {
      const data = await apiFetch<Invitation[]>(
        `/organisations/${currentOrg.id}/invitations`,
        { token }
      );
      setInvitations(data.filter((inv) => inv.status === "pending"));
    } catch {
      setInvitations([]);
    }
  }, [currentOrg, token]);

  const fetchMembers = useCallback(async () => {
    if (!currentOrg || !token) return;
    setLoadingMembers(true);
    try {
      const data = await apiFetch<Membership[]>(
        `/organisations/${currentOrg.id}/members`,
        { token }
      );
      setMembers(data);
      const myMembership = data.find(
        (m) => m.user_id === session?.user?.id
      );
      setIsOrgManager(
        session?.user?.role === "admin" ||
          myMembership?.role_in_org === "manager"
      );
    } catch {
      setMembers([]);
    } finally {
      setLoadingMembers(false);
    }
  }, [currentOrg, token, session?.user?.id, session?.user?.role]);

  useEffect(() => {
    fetchMembers();
    fetchInvitations();
  }, [fetchMembers, fetchInvitations]);

  if (!currentOrg) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Organisation</h1>
        <p className="text-muted-foreground">
          Aucune organisation sélectionnée. Créez ou rejoignez une
          organisation.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Organisation</h1>

      {/* Org info card */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>{currentOrg.name}</CardTitle>
            <CardDescription>
              Créée le{" "}
              {new Date(currentOrg.created_at).toLocaleDateString("fr-FR")}
            </CardDescription>
          </div>
          {isOrgManager && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="mr-2 h-4 w-4" />
              Modifier
            </Button>
          )}
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-sm text-muted-foreground">Forme juridique</p>
            <p className="font-medium">
              {currentOrg.forme_juridique ?? "Non renseignée"}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Taille</p>
            <p className="font-medium">
              {currentOrg.taille
                ? `${currentOrg.taille} salariés`
                : "Non renseignée"}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Members section */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>Membres</CardTitle>
            <CardDescription>{members.length} membre(s)</CardDescription>
          </div>
          {isOrgManager && (
            <Button size="sm" onClick={() => setInviteOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Inviter un membre
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {loadingMembers ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nom</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Rôle</TableHead>
                  {isOrgManager && (
                    <TableHead className="text-right">Actions</TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => (
                  <MemberRow
                    key={member.id}
                    member={member}
                    isOrgManager={isOrgManager}
                    orgId={currentOrg.id}
                    token={token!}
                    onUpdated={fetchMembers}
                    currentUserId={session?.user?.id ?? ""}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pending invitations section */}
      {isOrgManager && invitations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Invitations en attente</CardTitle>
            <CardDescription>
              {invitations.length} invitation(s) en attente
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Rôle</TableHead>
                  <TableHead>Envoyé le</TableHead>
                  <TableHead>Expire le</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.map((inv) => (
                  <InvitationRow
                    key={inv.id}
                    invitation={inv}
                    orgId={currentOrg.id}
                    token={token!}
                    onUpdated={fetchInvitations}
                  />
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

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
            <Button
              variant="destructive"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Supprimer l&apos;organisation
            </Button>
          </CardContent>
        </Card>
      )}

      {isOrgManager && (
        <>
          <EditOrgDialog
            open={editOpen}
            onOpenChange={setEditOpen}
            org={currentOrg}
            token={token!}
            onUpdated={refetchOrgs}
          />
          <InviteMemberDialog
            open={inviteOpen}
            onOpenChange={setInviteOpen}
            orgId={currentOrg.id}
            token={token!}
            onInvited={fetchInvitations}
          />
          <DeleteOrgDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            org={currentOrg}
            token={token!}
            onDeleted={handleOrgDeleted}
          />
        </>
      )}
    </div>
  );
}

// --- MemberRow ---

function MemberRow({
  member,
  isOrgManager,
  orgId,
  token,
  onUpdated,
  currentUserId,
}: {
  member: Membership;
  isOrgManager: boolean;
  orgId: string;
  token: string;
  onUpdated: () => void;
  currentUserId: string;
}) {
  const isSelf = member.user_id === currentUserId;

  async function toggleRole() {
    const newRole =
      member.role_in_org === "manager" ? "user" : "manager";
    await apiFetch(`/organisations/${orgId}/members/${member.id}`, {
      method: "PATCH",
      token,
      body: JSON.stringify({ role_in_org: newRole }),
    });
    onUpdated();
  }

  async function removeMember() {
    await apiFetch(`/organisations/${orgId}/members/${member.id}`, {
      method: "DELETE",
      token,
    });
    onUpdated();
  }

  return (
    <TableRow>
      <TableCell className="font-medium">
        {member.user_full_name ?? "—"}
      </TableCell>
      <TableCell>{member.user_email}</TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={member.role_in_org === "manager" ? "rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]" : "rounded-full"}
        >
          {member.role_in_org === "manager" ? "Manager" : "Utilisateur"}
        </Badge>
      </TableCell>
      {isOrgManager && (
        <TableCell className="text-right">
          {!isSelf && (
            <div className="flex justify-end gap-1">
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleRole}
                title="Changer le rôle"
              >
                <UserCog className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={removeMember}
                title="Retirer"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          )}
        </TableCell>
      )}
    </TableRow>
  );
}

// --- EditOrgDialog ---

function EditOrgDialog({
  open,
  onOpenChange,
  org,
  token,
  onUpdated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  org: { id: string; name: string; forme_juridique: string | null; taille: string | null };
  token: string;
  onUpdated: () => Promise<void>;
}) {
  const [name, setName] = useState(org.name);
  const [formeJuridique, setFormeJuridique] = useState(
    org.forme_juridique ?? ""
  );
  const [taille, setTaille] = useState(org.taille ?? "");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setName(org.name);
    setFormeJuridique(org.forme_juridique ?? "");
    setTaille(org.taille ?? "");
  }, [org]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await apiFetch(`/organisations/${org.id}`, {
        method: "PATCH",
        token,
        body: JSON.stringify({
          name: name.trim(),
          forme_juridique: formeJuridique || null,
          taille: taille || null,
        }),
      });
      await onUpdated();
      onOpenChange(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modifier l&apos;organisation</DialogTitle>
          <DialogDescription>
            Mettez à jour les informations de votre organisation.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-name">Nom *</Label>
            <Input
              id="edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-forme">Forme juridique</Label>
            <Select value={formeJuridique} onValueChange={setFormeJuridique}>
              <SelectTrigger id="edit-forme">
                <SelectValue placeholder="Sélectionner..." />
              </SelectTrigger>
              <SelectContent>
                {FORME_JURIDIQUE_OPTIONS.map((fj) => (
                  <SelectItem key={fj} value={fj}>
                    {fj}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-taille">Taille</Label>
            <Select value={taille} onValueChange={setTaille}>
              <SelectTrigger id="edit-taille">
                <SelectValue placeholder="Nombre de salariés..." />
              </SelectTrigger>
              <SelectContent>
                {TAILLE_OPTIONS.map((t) => (
                  <SelectItem key={t} value={t}>
                    {t} salariés
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={submitting || !name.trim()}>
              {submitting ? "Enregistrement..." : "Enregistrer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// --- DeleteOrgDialog ---

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
    } catch {
      toast.error("Erreur lors de la suppression");
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
            <Button
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
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

// --- InviteMemberDialog ---

function InviteMemberDialog({
  open,
  onOpenChange,
  orgId,
  token,
  onInvited,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  orgId: string;
  token: string;
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("user");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch(`/organisations/${orgId}/invitations`, {
        method: "POST",
        token,
        body: JSON.stringify({ email, role_in_org: role }),
      });
      onInvited();
      onOpenChange(false);
      setEmail("");
      setRole("user");
    } catch {
      setError("Déjà membre ou invitation en attente pour cet email.");
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
            Un email d&apos;invitation sera envoyé à cette adresse.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="invite-email">Email *</Label>
            <Input
              id="invite-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@exemple.fr"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invite-role">Rôle</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id="invite-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">Utilisateur</SelectItem>
                <SelectItem value="manager">Manager</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !email.trim()}>
              {submitting ? "Invitation..." : "Inviter"}
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
  orgId,
  token,
  onUpdated,
}: {
  invitation: Invitation;
  orgId: string;
  token: string;
  onUpdated: () => void;
}) {
  const [resending, setResending] = useState(false);

  async function handleResend() {
    setResending(true);
    try {
      await apiFetch(
        `/organisations/${orgId}/invitations/${invitation.id}/resend`,
        { method: "POST", token }
      );
      onUpdated();
    } finally {
      setResending(false);
    }
  }

  async function handleCancel() {
    await apiFetch(
      `/organisations/${orgId}/invitations/${invitation.id}`,
      { method: "DELETE", token }
    );
    onUpdated();
  }

  return (
    <TableRow>
      <TableCell>{invitation.email}</TableCell>
      <TableCell>
        <Badge variant={invitation.role_in_org === "manager" ? "secondary" : "outline"}>
          {invitation.role_in_org === "manager" ? "Manager" : "Utilisateur"}
        </Badge>
      </TableCell>
      <TableCell>
        {new Date(invitation.created_at).toLocaleDateString("fr-FR")}
      </TableCell>
      <TableCell>
        {new Date(invitation.expires_at).toLocaleDateString("fr-FR")}
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
            <RotateCw className={`h-4 w-4 ${resending ? "animate-spin" : ""}`} />
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
