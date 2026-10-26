"use client";

import { useSession } from "next-auth/react";
import { Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowUpRight, Search, Users } from "lucide-react";
import { AdminPageHeader } from "@/components/admin/page-header";
import { TechnicalCosts } from "@/components/admin/technical-costs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SandboxRunner } from "../quality/SandboxRunner";
import { VectorIndex } from "@/components/admin/vector-index";

function ToolsContent() {
  const { data: session } = useSession();
  const canManageCosts =
    Boolean(session?.user) && session?.user?.staff_role !== "tech";
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab =
    requested &&
    (canManageCosts
      ? ["sandbox", "index", "costs"]
      : ["sandbox", "index"]
    ).includes(requested)
      ? requested
      : "sandbox";
  return (
    <div className="space-y-6">
      <AdminPageHeader
        section="Exploitation"
        title="Outils techniques"
        description={
          canManageCosts
            ? "Testez une question, inspectez l’index et gérez les réglages du moteur IA."
            : "Testez une question et inspectez l’index documentaire."
        }
      />
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" asChild>
          <Link href="/recherche">
            <Search className="size-4" />
            Ouvrir la recherche dans l’application
            <ArrowUpRight className="size-4" />
          </Link>
        </Button>
        {canManageCosts && (
          <Button variant="outline" size="sm" asChild>
            <Link href="/admin/users">
              <Users className="size-4" />
              Comptes & membres
            </Link>
          </Button>
        )}
      </div>
      <Tabs
        value={tab}
        onValueChange={(value) =>
          router.replace(`/admin/tools?tab=${value}`, { scroll: false })
        }
        className="gap-6"
      >
        <div className="overflow-x-auto">
          <TabsList
            variant="line"
            aria-label="Outils techniques"
            className="h-11 gap-4 border-b"
          >
            <TabsTrigger value="sandbox">Test manuel</TabsTrigger>
            <TabsTrigger value="index">Index documentaire</TabsTrigger>
            {canManageCosts && (
              <TabsTrigger value="costs">Coûts & réglages IA</TabsTrigger>
            )}
          </TabsList>
        </div>
        <TabsContent value="sandbox">
          <SandboxRunner />
        </TabsContent>
        <TabsContent value="index">
          <VectorIndex embedded />
        </TabsContent>
        {canManageCosts && (
          <TabsContent value="costs">
            <TechnicalCosts embedded />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}

export default function ToolsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <ToolsContent />
    </Suspense>
  );
}
