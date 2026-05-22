"use client";

import { useState } from "react";
import { Building2, Plus, ChevronsUpDown, Check } from "lucide-react";
import { useSession } from "next-auth/react";
import { useOrg } from "@/lib/org-context";
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

export function OrgSelector() {
  const { data: session } = useSession();
  const {
    organisations,
    currentOrg,
    setCurrentOrgId,
    loading,
    workspaceName,
    createOrganisation,
  } = useOrg();
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  // Can create orgs: admin, workspace owner, or invited manager in a workspace
  const isAdmin = session?.user?.role === "admin";
  const isManager = session?.user?.role === "manager";
  const hasWorkspace = !!workspaceName;
  const canCreate = isAdmin || isManager || hasWorkspace;

  if (loading) {
    return (
      <Button variant="outline" className="w-full justify-between" disabled>
        <span className="text-muted-foreground">Chargement...</span>
      </Button>
    );
  }

  // Empty state: bouton violet à la place de la dropdown quand pas d'org
  if (organisations.length === 0 && canCreate) {
    return (
      <>
        <Button
          className="w-full bg-[#652bb0] text-white hover:bg-[#5a2599] focus-visible:ring-[#652bb0]/40"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="mr-2 h-4 w-4" />
          Créer une organisation
        </Button>
        <OrgFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={async (data) => {
            await createOrganisation(data);
          }}
        />
      </>
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
            await createOrganisation(data);
          }}
        />
      )}
    </>
  );
}
