"use client";

import { useState } from "react";
import Image from "next/image";
import { Building2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useOrg } from "@/lib/org-context";
import { OrgFormDialog } from "@/components/org-form-dialog";

export function NoOrgWelcome() {
  const { createOrganisation, canCreateOrganisation } = useOrg();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div className="dark:bg-card animate-in fade-in flex flex-1 flex-col items-center justify-center rounded-xl bg-white px-4 duration-500">
      <div className="animate-in fade-in zoom-in-95 mb-6 duration-500">
        <Image
          src="/icon-aoria-dark.svg"
          alt="AORIA RH"
          width={48}
          height={48}
          priority
          className="dark:hidden"
        />
        <Image
          src="/icon-aoria-white.svg"
          alt="AORIA RH"
          width={48}
          height={48}
          priority
          className="hidden dark:block"
        />
      </div>
      <h1 className="animate-in fade-in slide-in-from-bottom-2 text-2xl font-semibold tracking-tight delay-100 duration-500">
        Bienvenue sur AORIA&nbsp;RH
      </h1>
      <p className="text-muted-foreground animate-in fade-in slide-in-from-bottom-2 mt-3 max-w-md text-center text-sm delay-150 duration-500">
        {canCreateOrganisation
          ? "Pour commencer, créez votre première organisation : nom, taille et convention collective (facultatif)."
          : "Vous n'avez pas encore accès à une organisation. Acceptez votre invitation ou contactez le propriétaire de votre espace de travail."}
      </p>

      {canCreateOrganisation && (
        <div className="animate-in fade-in slide-in-from-bottom-2 mt-8 flex flex-col items-center gap-3 delay-200 duration-500">
          <Button
            size="lg"
            className="rounded-xl bg-[#652bb0] px-6 py-6 text-base font-semibold text-white shadow-sm hover:bg-[#5a2599] focus-visible:ring-[#652bb0]/40"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="mr-2 h-5 w-5" />
            Créer une organisation
          </Button>
          <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <Building2 className="h-3.5 w-3.5" />
            Vous pourrez en ajouter d&apos;autres ensuite
          </p>
        </div>
      )}

      {canCreateOrganisation && (
        <OrgFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={async (data) => {
            await createOrganisation(data);
          }}
        />
      )}
    </div>
  );
}
