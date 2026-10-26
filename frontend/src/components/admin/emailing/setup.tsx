"use client";

import { ArrowRight, FileText, GitBranch, Send, Users } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import CampaignsPanel from "./campaigns-panel";
import ListsPanel from "./lists-panel";
import SequencesPanel from "./sequences-panel";
import TemplatesPanel from "./templates-panel";

const SECTIONS = [
  {
    id: "lists",
    label: "Contacts",
    description: "Votre audience dans Brevo",
    icon: Users,
  },
  {
    id: "templates",
    label: "Modèles d’emails",
    description: "Le contenu de vos messages",
    icon: FileText,
  },
  {
    id: "sequences",
    label: "Séquences",
    description: "L’ordre et les délais des emails",
    icon: GitBranch,
  },
  {
    id: "campaigns",
    label: "Campagnes",
    description: "La programmation des envois",
    icon: Send,
  },
] as const;

export type SetupSection = (typeof SECTIONS)[number]["id"];

export function EmailingSetup({
  initialSection = "campaigns",
}: {
  initialSection?: SetupSection;
}) {
  const [section, setSection] = useState<SetupSection>(initialSection);
  const index = SECTIONS.findIndex((item) => item.id === section);
  const next = SECTIONS[index + 1];

  function selectSection(value: string) {
    const target = SECTIONS.find((item) => item.id === value);
    if (!target) return;
    setSection(target.id);
    const url = new URL(window.location.href);
    url.searchParams.set("section", target.id);
    window.history.replaceState(null, "", url);
  }

  return (
    <Tabs
      value={section}
      onValueChange={selectSection}
      className="gap-6"
      activationMode="manual"
    >
      <div className="space-y-3">
        <p className="text-muted-foreground text-sm">
          Pour une nouvelle campagne : vérifiez vos contacts, préparez vos
          emails, puis assemblez votre séquence. Vos ressources sont
          réutilisables.
        </p>
        <TabsList
          aria-label="Préparation des campagnes"
          className="grid h-auto! w-full grid-cols-2 gap-2 rounded-xl bg-transparent p-0 lg:grid-cols-4"
        >
          {SECTIONS.map(({ id, label, description, icon: Icon }, i) => (
            <TabsTrigger
              key={id}
              value={id}
              className="bg-background data-[state=active]:border-primary/40 data-[state=active]:bg-primary/5 h-full min-h-24 items-start justify-start gap-3 rounded-xl border p-4 text-left whitespace-normal data-[state=active]:shadow-none"
            >
              <span className="bg-muted flex size-9 shrink-0 items-center justify-center rounded-lg">
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <span className="min-w-0 space-y-1">
                <span className="block text-sm font-semibold">
                  <span className="text-muted-foreground mr-1 text-xs">
                    {i + 1}.
                  </span>
                  {label}
                </span>
                <span className="text-muted-foreground hidden text-xs font-normal sm:block">
                  {description}
                </span>
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </div>
      <TabsContent value="lists">
        <ListsPanel />
      </TabsContent>
      <TabsContent value="templates">
        <TemplatesPanel />
      </TabsContent>
      <TabsContent value="sequences">
        <SequencesPanel />
      </TabsContent>
      <TabsContent value="campaigns">
        <CampaignsPanel onPrepare={selectSection} />
      </TabsContent>
      {next && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-muted-foreground text-sm">Prêt pour la suite ?</p>
          <Button variant="outline" onClick={() => selectSection(next.id)}>
            {next.label} <ArrowRight className="size-4" />
          </Button>
        </div>
      )}
    </Tabs>
  );
}
