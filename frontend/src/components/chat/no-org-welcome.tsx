"use client";

import { useState } from "react";
import Image from "next/image";
import { Building2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useOrg } from "@/lib/org-context";
import { OrgFormDialog } from "@/components/org-form-dialog";

export function NoOrgWelcome() {
  const { createOrganisation } = useOrg();
  const [createOpen, setCreateOpen] = useState(false);

  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-xl bg-white px-4 dark:bg-card animate-in fade-in duration-500">
      <div className="mb-6 animate-in fade-in zoom-in-95 duration-500">
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
      <h1 className="text-2xl font-semibold tracking-tight animate-in fade-in slide-in-from-bottom-2 duration-500 delay-100">
        Bienvenue sur AORIA&nbsp;RH
      </h1>
      <p className="text-muted-foreground mt-3 max-w-md text-center text-sm animate-in fade-in slide-in-from-bottom-2 duration-500 delay-150">
        Pour commencer, créez votre première organisation. Cela ne prend qu&apos;une minute&nbsp;: nom, taille et convention collective (facultatif).
      </p>

      <div className="mt-8 flex flex-col items-center gap-3 animate-in fade-in slide-in-from-bottom-2 duration-500 delay-200">
        <Button
          size="lg"
          className="bg-[#652bb0] text-white hover:bg-[#5a2599] focus-visible:ring-[#652bb0]/40 px-6 py-6 text-base font-semibold rounded-xl shadow-sm"
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

      <OrgFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSubmit={async (data) => {
          await createOrganisation(data);
        }}
      />
    </div>
  );
}
