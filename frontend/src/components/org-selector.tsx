"use client";

import { useEffect, useState } from "react";
import { Building2, Plus, ChevronsUpDown, Check } from "lucide-react";
import { useSession } from "next-auth/react";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { FORME_JURIDIQUE_OPTIONS, TAILLE_OPTIONS } from "@/types/api";
import type { Organisation } from "@/types/api";

export function OrgSelector() {
  const { data: session } = useSession();
  const { organisations, currentOrg, setCurrentOrgId, loading, refetchOrgs } =
    useOrg();
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const canCreate =
    session?.user?.role === "admin" || session?.user?.role === "manager";

  // Auto-open create dialog when user has no organisations
  useEffect(() => {
    if (!loading && organisations.length === 0 && canCreate) {
      setCreateOpen(true);
    }
  }, [loading, organisations.length, canCreate]);

  if (loading) {
    return (
      <Button variant="outline" className="w-full justify-between" disabled>
        <span className="text-muted-foreground">Chargement...</span>
      </Button>
    );
  }

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" className="w-full justify-between">
            <div className="flex items-center gap-2 truncate">
              <Building2 className="h-4 w-4 shrink-0" />
              <span className="truncate">
                {currentOrg?.name ?? "Aucune organisation"}
              </span>
            </div>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-0" align="start">
          <Command>
            <CommandList>
              <CommandGroup heading="Mes organisations">
                {organisations.map((org) => (
                  <CommandItem
                    key={org.id}
                    onSelect={() => {
                      setCurrentOrgId(org.id);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        currentOrg?.id === org.id
                          ? "opacity-100"
                          : "opacity-0"
                      )}
                    />
                    {org.name}
                  </CommandItem>
                ))}
              </CommandGroup>
              {canCreate && (
                <>
                  <CommandSeparator />
                  <CommandGroup>
                    <CommandItem
                      onSelect={() => {
                        setOpen(false);
                        setCreateOpen(true);
                      }}
                    >
                      <Plus className="mr-2 h-4 w-4" />
                      Créer une organisation
                    </CommandItem>
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {canCreate && (
        <CreateOrgDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={async (org) => {
            await refetchOrgs();
            setCurrentOrgId(org.id);
          }}
        />
      )}
    </>
  );
}

interface CreateOrgDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (org: Organisation) => Promise<void>;
}

function CreateOrgDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateOrgDialogProps) {
  const { data: session } = useSession();
  const [name, setName] = useState("");
  const [formeJuridique, setFormeJuridique] = useState<string>("");
  const [taille, setTaille] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const org = await apiFetch<Organisation>("/organisations/", {
        method: "POST",
        token: session?.access_token,
        body: JSON.stringify({
          name: name.trim(),
          forme_juridique: formeJuridique || null,
          taille: taille || null,
        }),
      });
      await onCreated(org);
      onOpenChange(false);
      setName("");
      setFormeJuridique("");
      setTaille("");
    } catch {
      setError("Erreur lors de la création de l'organisation");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Créer une organisation</DialogTitle>
          <DialogDescription>
            Renseignez les informations de votre organisation.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="org-name">Nom *</Label>
            <Input
              id="org-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Nom de l'organisation"
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="forme-juridique">Forme juridique</Label>
            <Select value={formeJuridique} onValueChange={setFormeJuridique}>
              <SelectTrigger id="forme-juridique">
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
            <Label htmlFor="taille">Taille</Label>
            <Select value={taille} onValueChange={setTaille}>
              <SelectTrigger id="taille">
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
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="submit" disabled={submitting || !name.trim()}>
              {submitting ? "Création..." : "Créer"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
