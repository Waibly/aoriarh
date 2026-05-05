"use client";

import { useEffect, useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { Pencil, KeyRound, Briefcase, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api";
import { useOrg } from "@/lib/org-context";
import type { User } from "@/types/api";
import { PROFIL_METIER_OPTIONS } from "@/types/api";
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
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrateur",
  manager: "Manager",
  user: "Utilisateur",
};

export default function AccountPage() {
  const { data: session, update: updateSession } = useSession();
  const token = session?.access_token;

  const { workspaceName, setWorkspaceName } = useOrg();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [workspaceEditOpen, setWorkspaceEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiFetch<User>("/users/me", { token })
      .then(setUser)
      .catch(() => toast.error("Erreur lors du chargement du profil"))
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">Mon compte</h1>
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-4 w-32" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-36" />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!user) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">Mon compte</h1>
        <p className="text-muted-foreground">Impossible de charger le profil.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Mon compte</h1>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="space-y-1.5">
            <CardTitle>Informations personnelles</CardTitle>
            <CardDescription>Vos informations de profil</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
            <Pencil className="mr-2 h-4 w-4" />
            Modifier
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 text-sm text-muted-foreground">Nom</span>
            <span className="text-sm font-medium">{user.full_name}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 text-sm text-muted-foreground">Email</span>
            <span className="text-sm font-medium truncate min-w-0">{user.email}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 text-sm text-muted-foreground">Rôle</span>
            <Badge variant="outline" className={
              user.role === "admin" ? "rounded-full border-amber-400 bg-amber-50 text-amber-700 dark:border-amber-500 dark:bg-amber-950 dark:text-amber-300" :
              user.role === "manager" ? "rounded-full border-[#652bb0] bg-[#652bb0]/10 text-[#652bb0]" :
              "rounded-full"
            }>{ROLE_LABELS[user.role] ?? user.role}</Badge>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 text-sm text-muted-foreground">Profil métier</span>
            <span className="text-sm font-medium">
              {PROFIL_METIER_OPTIONS.find((p) => p.value === user.profil_metier)?.label ?? "Non renseigné"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-32 shrink-0 text-sm text-muted-foreground">Membre depuis</span>
            <span className="text-sm font-medium">
              {new Date(user.created_at).toLocaleDateString("fr-FR", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Espace de travail — visible pour tous, éditable par manager/admin */}
      {workspaceName && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="space-y-1.5">
              <CardTitle className="flex items-center gap-2">
                <Briefcase className="h-5 w-5" />
                Espace de travail
              </CardTitle>
              <CardDescription>
                Votre espace de travail regroupe toutes vos organisations et les
                membres de votre équipe.
              </CardDescription>
            </div>
            {(user.role === "manager" || user.role === "admin") && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setWorkspaceEditOpen(true)}
              >
                <Pencil className="mr-2 h-4 w-4" />
                Renommer
              </Button>
            )}
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <span className="w-32 shrink-0 text-sm text-muted-foreground">Nom</span>
              <span className="text-sm font-medium">{workspaceName}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {user.auth_provider === "credentials" && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="space-y-1.5">
              <CardTitle>Sécurité</CardTitle>
              <CardDescription>Gérez votre mot de passe</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => setPasswordOpen(true)}>
              <KeyRound className="mr-2 h-4 w-4" />
              Changer le mot de passe
            </Button>
          </CardHeader>
        </Card>
      )}

      {user.auth_provider === "google" && (
        <Card>
          <CardHeader>
            <CardTitle>Connexion</CardTitle>
            <CardDescription>
              Vous êtes connecté via Google. Aucun mot de passe à gérer.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {user.role !== "admin" && (
        <Card className="border-destructive/40">
          <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1.5">
              <CardTitle className="text-destructive">Zone dangereuse</CardTitle>
              <CardDescription>
                La suppression de votre compte est définitive. Toutes vos
                organisations, documents et conversations seront effacés.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive border-destructive/40 self-start sm:self-auto"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Supprimer mon compte
            </Button>
          </CardHeader>
        </Card>
      )}

      <DeleteAccountDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        token={token}
        isOwner={Boolean(workspaceName)}
      />

      <EditProfileDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        user={user}
        token={token}
        onSaved={async (updated) => {
          setUser(updated);
          await updateSession({
            user: { full_name: updated.full_name, email: updated.email },
          });
          toast.success("Profil mis à jour");
        }}
      />

      <ChangePasswordDialog
        open={passwordOpen}
        onOpenChange={setPasswordOpen}
        token={token}
      />

      <RenameWorkspaceDialog
        open={workspaceEditOpen}
        onOpenChange={setWorkspaceEditOpen}
        currentName={workspaceName ?? ""}
        token={token}
        onSaved={(newName) => {
          setWorkspaceName(newName);
          toast.success("Espace de travail renommé");
        }}
      />
    </div>
  );
}

/* ---- Edit Profile Dialog ---- */

interface EditProfileDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: User;
  token?: string;
  onSaved: (user: User) => Promise<void>;
}

function EditProfileDialog({
  open,
  onOpenChange,
  user,
  token,
  onSaved,
}: EditProfileDialogProps) {
  const [fullName, setFullName] = useState(user.full_name);
  const [email, setEmail] = useState(user.email);
  const [profilMetier, setProfilMetier] = useState(user.profil_metier ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setFullName(user.full_name);
      setEmail(user.email);
      setProfilMetier(user.profil_metier ?? "");
      setError(null);
    }
  }, [open, user]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const updated = await apiFetch<User>("/users/me", {
        method: "PATCH",
        token,
        body: JSON.stringify({
          full_name: fullName.trim(),
          email: email.trim(),
          profil_metier: profilMetier || null,
        }),
      });
      await onSaved(updated);
      onOpenChange(false);
    } catch {
      setError("Erreur lors de la mise à jour du profil");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modifier le profil</DialogTitle>
          <DialogDescription>
            Mettez à jour vos informations personnelles.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="full-name">Nom complet</Label>
            <Input
              id="full-name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="profil-metier">Profil métier</Label>
            <Select value={profilMetier} onValueChange={setProfilMetier}>
              <SelectTrigger id="profil-metier">
                <SelectValue placeholder="Sélectionner votre profil..." />
              </SelectTrigger>
              <SelectContent>
                {PROFIL_METIER_OPTIONS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Permet d&apos;adapter les réponses juridiques à votre perspective métier.
            </p>
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !fullName.trim()}>
              {submitting ? "Enregistrement..." : "Enregistrer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ---- Change Password Dialog ---- */

interface ChangePasswordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token?: string;
}

function ChangePasswordDialog({
  open,
  onOpenChange,
  token,
}: ChangePasswordDialogProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setError(null);
    }
  }, [open]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("Les mots de passe ne correspondent pas");
      return;
    }
    if (newPassword.length < 6) {
      setError("Le nouveau mot de passe doit faire au moins 6 caractères");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/users/me/password", {
        method: "POST",
        token,
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      toast.success("Mot de passe modifié");
      onOpenChange(false);
    } catch {
      setError("Mot de passe actuel incorrect");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Changer le mot de passe</DialogTitle>
          <DialogDescription>
            Saisissez votre mot de passe actuel puis le nouveau.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="current-password">Mot de passe actuel</Label>
            <Input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">Nouveau mot de passe</Label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Confirmer le mot de passe</Label>
            <Input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="submit"
              disabled={submitting || !currentPassword || !newPassword || !confirmPassword}
            >
              {submitting ? "Modification..." : "Modifier"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ---- Rename Workspace Dialog ---- */

interface RenameWorkspaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentName: string;
  token?: string;
  onSaved: (newName: string) => void;
}

function RenameWorkspaceDialog({
  open,
  onOpenChange,
  currentName,
  token,
  onSaved,
}: RenameWorkspaceDialogProps) {
  const [name, setName] = useState(currentName);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(currentName);
      setError(null);
    }
  }, [open, currentName]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await apiFetch<{ name: string }>("/users/me/workspace", {
        method: "PUT",
        token,
        body: JSON.stringify({ name: name.trim() }),
      });
      onSaved(res.name);
      onOpenChange(false);
    } catch {
      setError("Erreur lors du renommage");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Renommer l&apos;espace de travail</DialogTitle>
          <DialogDescription>
            Ce nom est visible par tous les membres de votre équipe.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="workspace-name">Nom</Label>
            <Input
              id="workspace-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ex : Waibly, Mon cabinet RH"
              required
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
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

/* ---- Delete Account Dialog ---- */

const DELETE_PHRASE = "SUPPRIMER MON COMPTE";

interface DeleteAccountDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  token?: string;
  /** True if the user owns a workspace (manager). Used to warn that all
   * organisations, documents and conversations of the workspace will be
   * irreversibly deleted along with the user. */
  isOwner: boolean;
}

function DeleteAccountDialog({
  open,
  onOpenChange,
  token,
  isOwner,
}: DeleteAccountDialogProps) {
  const [confirmation, setConfirmation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setConfirmation("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (confirmation !== DELETE_PHRASE) return;
    setError(null);
    setSubmitting(true);
    try {
      await apiFetch("/users/me", {
        method: "DELETE",
        token,
        body: JSON.stringify({ confirmation }),
      });
      // Don't toast — the redirect will signal success.
      await signOut({ callbackUrl: "/login" });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Impossible de supprimer le compte. Réessayez ou contactez le support.",
      );
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-destructive">
            Supprimer définitivement votre compte
          </DialogTitle>
          <DialogDescription>
            Cette action est irréversible.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm space-y-2">
            <p className="font-medium">Ce qui sera supprimé :</p>
            <ul className="list-disc pl-5 space-y-1 text-muted-foreground">
              <li>Votre compte utilisateur et vos données personnelles</li>
              {isOwner && (
                <>
                  <li>
                    Toutes les organisations de votre espace de travail
                  </li>
                  <li>Tous les documents importés et leurs vecteurs</li>
                  <li>L&apos;historique de toutes les conversations</li>
                  <li>Les membres invités sur votre espace de travail</li>
                </>
              )}
            </ul>
            {isOwner && (
              <p className="text-xs text-muted-foreground pt-1">
                Si vous avez un abonnement payant actif, pensez à le résilier
                au préalable depuis{" "}
                <a
                  href="/billing"
                  className="underline hover:text-foreground"
                >
                  Abonnement
                </a>{" "}
                pour éviter une facturation parallèle.
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="delete-confirmation">
              Tapez{" "}
              <span className="font-mono font-semibold">{DELETE_PHRASE}</span>{" "}
              pour confirmer
            </Label>
            <Input
              id="delete-confirmation"
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
              autoFocus
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Annuler
            </Button>
            <Button
              type="submit"
              variant="destructive"
              disabled={submitting || confirmation !== DELETE_PHRASE}
            >
              {submitting ? "Suppression..." : "Supprimer définitivement"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
