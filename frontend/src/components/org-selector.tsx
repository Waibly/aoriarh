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
import { cn } from "@/lib/utils";
import { OrgFormDialog } from "@/components/org-form-dialog";
import type { Organisation } from "@/types/api";

export function OrgSelector() {
  const { data: session } = useSession();
  const { organisations, currentOrg, setCurrentOrgId, loading, refetchOrgs, workspaceName } =
    useOrg();
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  // Can create orgs only if admin or workspace owner (manager with own workspace)
  const isAdmin = session?.user?.role === "admin";
  const isWorkspaceOwner = session?.user?.role === "manager" && !!workspaceName;
  const canCreate = isAdmin || isWorkspaceOwner;

  // Auto-open create dialog when workspace owner has no organisations
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
              {workspaceName && (
                <div className="px-3 py-2 border-b">
                  <p className="text-xs font-semibold text-muted-foreground truncate">
                    {workspaceName}
                  </p>
                </div>
              )}
              <CommandGroup heading="Organisations">
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
        <OrgFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={async (data) => {
            const { profil_metier, selectedCcn, ...orgData } = data;
            const org = await apiFetch<Organisation>("/organisations/", {
              method: "POST",
              token: session?.access_token,
              body: JSON.stringify(orgData),
            });
            // Save profil_metier on user if provided
            if (profil_metier) {
              await apiFetch("/users/me", {
                method: "PATCH",
                token: session?.access_token,
                body: JSON.stringify({ profil_metier }),
              });
            }
            // Install selected conventions collectives (fire & forget)
            if (selectedCcn && selectedCcn.length > 0) {
              for (const ccn of selectedCcn) {
                apiFetch(`/conventions/organisations/${org.id}`, {
                  method: "POST",
                  token: session?.access_token,
                  body: JSON.stringify({ idcc: ccn.idcc }),
                }).catch(() => {});
              }
            }
            await refetchOrgs();
            setCurrentOrgId(org.id);
          }}
        />
      )}
    </>
  );
}
