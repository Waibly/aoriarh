"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Pencil, Trash2, Info } from "lucide-react";
import { toast } from "sonner";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import type { Membership } from "@/types/api";
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
import { OrgFormDialog } from "@/components/org-form-dialog";

export default function OrganisationPage() {
  const { data: session } = useSession();
  const { currentOrg, refetchOrgs } = useOrg();
  const token = session?.access_token;
  const router = useRouter();

  const [members, setMembers] = useState<Membership[]>([]);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isOrgManager, setIsOrgManager] = useState(false);

  const handleOrgDeleted = useCallback(async () => {
    await refetchOrgs();
    router.push("/chat");
  }, [refetchOrgs, router]);

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
  }, [fetchMembers]);

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
            <p className="text-sm text-muted-foreground">Effectif</p>
            <p className="font-medium">
              {currentOrg.taille
                ? `${currentOrg.taille} salariés`
                : "Non renseigné"}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Convention collective</p>
            <p className="font-medium">
              {currentOrg.convention_collective ?? "Non renseignée"}
            </p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Secteur d&apos;activité</p>
            <p className="font-medium">
              {currentOrg.secteur_activite ?? "Non renseigné"}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Members section (read-only) */}
      <Card>
        <CardHeader>
          <div className="space-y-1.5">
            <CardTitle>Membres</CardTitle>
            <CardDescription>{members.length} membre(s) dans cette organisation</CardDescription>
          </div>
          {isOrgManager && (
            <div className="flex items-start gap-2 rounded-md border border-border bg-muted/50 p-3 mt-3">
              <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
              <p className="text-sm text-muted-foreground">
                La gestion des membres (ajout, modification, suppression) se fait depuis la page{" "}
                <Button
                  variant="link"
                  className="h-auto p-0 text-sm"
                  onClick={() => router.push("/team")}
                >
                  Équipe
                </Button>.
              </p>
            </div>
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
                        className={member.role_in_org === "manager" ? "rounded-full border-[#9952b8] bg-[#9952b8]/10 text-[#9952b8]" : "rounded-full"}
                      >
                        {member.role_in_org === "manager" ? "Manager" : "Utilisateur"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
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
          <OrgFormDialog
            open={editOpen}
            onOpenChange={setEditOpen}
            org={currentOrg}
            onSubmit={async (data) => {
              await apiFetch(`/organisations/${currentOrg.id}`, {
                method: "PATCH",
                token: token!,
                body: JSON.stringify(data),
              });
              await refetchOrgs();
            }}
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
