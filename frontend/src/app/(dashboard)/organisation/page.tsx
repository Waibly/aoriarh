"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { Building2, ChevronRight, FileText, Plus, Users } from "lucide-react";
import { toast } from "@/lib/toast";
import { useOrg } from "@/lib/org-context";
import { apiFetch } from "@/lib/api";
import type { Organisation } from "@/types/api";
import {
  fetchUsageSummary,
  fetchAddons,
  fetchQuota,
  type UsageSummary,
  type ActiveAddon,
  type QuotaInfo,
} from "@/lib/billing-api";
import { LimitReachedDialog } from "@/components/limit-reached-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { OrgFormDialog } from "@/components/org-form-dialog";

export default function OrganisationListPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const router = useRouter();
  const { organisations, loading, createOrganisation, canCreateOrganisation } =
    useOrg();

  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [addons, setAddons] = useState<ActiveAddon[]>([]);
  const [quota, setQuota] = useState<QuotaInfo | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [limitOpen, setLimitOpen] = useState(false);

  const fetchBillingState = useCallback(async () => {
    if (!token) return;
    try {
      const [u, a, q] = await Promise.all([
        fetchUsageSummary(token),
        fetchAddons(token),
        fetchQuota(token),
      ]);
      setUsage(u);
      setAddons(a);
      setQuota(q);
    } catch {
      // Silencieux — le backend restera le garde-fou.
    }
  }, [token]);

  useEffect(() => {
    fetchBillingState();
    const handler = () => fetchBillingState();
    window.addEventListener("quota-updated", handler);
    return () => window.removeEventListener("quota-updated", handler);
  }, [fetchBillingState]);

  const orgUsed = usage?.organisations.used ?? organisations.length;
  const orgIncluded = usage?.organisations.limit ?? 0;
  const orgAddonCount = addons
    .filter((a) => a.addon_type === "extra_org")
    .reduce((sum, a) => sum + a.quantity, 0);
  const orgLimitReached = orgUsed >= orgIncluded && orgIncluded > 0;
  const currentPlan = quota?.plan ?? "gratuit";
  const canCreateOrg = canCreateOrganisation;

  const handleCreateClick = () => {
    if (orgLimitReached) {
      setLimitOpen(true);
    } else {
      setCreateOpen(true);
    }
  };

  const pct = orgIncluded > 0 ? orgUsed / orgIncluded : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Organisations
          </h1>
          {usage && (
            <p className="text-muted-foreground mt-1 text-sm">
              <strong>{orgUsed}</strong> / {orgIncluded} organisation
              {orgIncluded > 1 ? "s" : ""} utilisée{orgUsed > 1 ? "s" : ""} sur
              votre plan
              {pct >= 0.8 && pct < 1 && (
                <span className="ml-2 inline-block rounded-full bg-orange-500/10 px-2 py-0.5 text-xs font-medium text-orange-600 dark:text-orange-400">
                  Proche de la limite
                </span>
              )}
            </p>
          )}
        </div>
        {canCreateOrg && (
          <Button onClick={handleCreateClick}>
            <Plus className="mr-2 h-4 w-4" />
            Créer une organisation
          </Button>
        )}
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : organisations.length === 0 ? (
        <Card>
          <CardContent className="space-y-3 py-12 text-center">
            <Building2 className="text-muted-foreground mx-auto h-10 w-10" />
            <p className="text-muted-foreground">
              Aucune organisation pour l&apos;instant. Créez-en une pour
              commencer à ajouter des documents et poser des questions.
            </p>
            {canCreateOrg && (
              <Button onClick={handleCreateClick}>
                <Plus className="mr-2 h-4 w-4" />
                Créer ma première organisation
              </Button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {organisations.map((o) => {
            const docEntry = usage?.documents_by_org.find(
              (d) => d.org_id === o.id
            );
            return (
              <OrgCard
                key={o.id}
                org={o}
                docCount={docEntry?.used ?? null}
                onClick={() => router.push(`/organisation/${o.id}`)}
              />
            );
          })}
        </div>
      )}

      {canCreateOrg && token && (
        <OrgFormDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onSubmit={async (data) => {
            const org = await createOrganisation(data);
            toast.success(`Organisation « ${org.name} » créée`);
            router.push(`/organisation/${org.id}`);
          }}
        />
      )}

      <LimitReachedDialog
        open={limitOpen}
        onOpenChange={setLimitOpen}
        resource="organisation"
        currentPlan={currentPlan}
        includedCount={orgIncluded}
        usedCount={orgUsed}
        activeAddonCount={orgAddonCount}
      />
    </div>
  );
}

function OrgCard({
  org,
  docCount,
  onClick,
}: {
  org: Organisation;
  docCount: number | null;
  onClick: () => void;
}) {
  const { data: session } = useSession();
  const token = session?.access_token;
  const [memberCount, setMemberCount] = useState<number | null>(null);

  useEffect(() => {
    if (!token) return;
    apiFetch<Array<unknown>>(`/organisations/${org.id}/members`, { token })
      .then((m) => setMemberCount(m.length))
      .catch(() => setMemberCount(null));
  }, [org.id, token]);

  const metaParts = [
    org.forme_juridique,
    org.taille ? `${org.taille} salariés` : null,
    org.secteur_activite,
  ].filter(Boolean);

  return (
    <Card
      className="hover:border-primary/60 cursor-pointer transition hover:shadow-sm"
      onClick={onClick}
    >
      <CardContent className="flex items-center gap-4 p-4">
        <div className="bg-primary/10 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg">
          <Building2 className="text-primary h-5 w-5" />
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="truncate font-semibold" title={org.name}>
            {org.name}
          </h3>
          {metaParts.length > 0 && (
            <p className="text-muted-foreground truncate text-xs">
              {metaParts.join(" · ")}
            </p>
          )}
        </div>

        <div className="text-muted-foreground hidden shrink-0 items-center gap-5 text-xs sm:flex">
          <div className="flex items-center gap-1.5" title="Membres">
            <Users className="h-3.5 w-3.5" />
            <span className="tabular-nums">
              {memberCount === null ? "…" : memberCount}
            </span>
          </div>
          <div className="flex items-center gap-1.5" title="Documents">
            <FileText className="h-3.5 w-3.5" />
            <span className="tabular-nums">
              {docCount === null ? "…" : docCount}
            </span>
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
        >
          Gérer
          <ChevronRight className="ml-1 h-3.5 w-3.5" />
        </Button>
      </CardContent>
    </Card>
  );
}
