"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  Building2,
  ChevronRight,
  FileText,
  Plus,
  Users,
} from "lucide-react";
import { toast } from "sonner";
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
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { OrgFormDialog } from "@/components/org-form-dialog";

export default function OrganisationListPage() {
  const { data: session } = useSession();
  const token = session?.access_token;
  const router = useRouter();
  const { organisations, loading, refetchOrgs, setCurrentOrgId } = useOrg();

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
  const canCreateOrg =
    session?.user?.role === "admin" || session?.user?.role === "manager";

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
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Organisations</h1>
          {usage && (
            <p className="text-sm text-muted-foreground mt-1">
              <strong>{orgUsed}</strong> / {orgIncluded} organisation
              {orgIncluded > 1 ? "s" : ""} utilisée{orgUsed > 1 ? "s" : ""} sur votre plan
              {pct >= 0.8 && pct < 1 && (
                <span className="ml-2 inline-block rounded-full bg-orange-500/10 text-orange-600 dark:text-orange-400 px-2 py-0.5 text-xs font-medium">
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
          <CardContent className="py-12 text-center space-y-3">
            <Building2 className="h-10 w-10 mx-auto text-muted-foreground" />
            <p className="text-muted-foreground">
              Aucune organisation pour l&apos;instant. Créez-en une pour commencer à ajouter des documents et poser des questions.
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {organisations.map((o) => {
            const docEntry = usage?.documents_by_org.find((d) => d.org_id === o.id);
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
            const { profil_metier, selectedCcn, ...orgData } = data;
            const org = await apiFetch<Organisation>("/organisations/", {
              method: "POST",
              token,
              body: JSON.stringify(orgData),
            });
            if (profil_metier) {
              await apiFetch("/users/me", {
                method: "PATCH",
                token,
                body: JSON.stringify({ profil_metier }),
              });
            }
            if (selectedCcn && selectedCcn.length > 0) {
              for (const ccn of selectedCcn) {
                apiFetch(`/conventions/organisations/${org.id}`, {
                  method: "POST",
                  token,
                  body: JSON.stringify({ idcc: ccn.idcc }),
                }).catch(() => {});
              }
            }
            if (typeof window !== "undefined") {
              window.dispatchEvent(new Event("quota-updated"));
            }
            await refetchOrgs();
            setCurrentOrgId(org.id);
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

  return (
    <Card
      className="cursor-pointer transition hover:border-primary/60 hover:shadow-md"
      onClick={onClick}
    >
      <CardContent className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <Building2 className="h-5 w-5 shrink-0 text-primary" />
            <h3 className="font-semibold truncate" title={org.name}>
              {org.name}
            </h3>
          </div>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        </div>

        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {org.forme_juridique && <span>{org.forme_juridique}</span>}
          {org.taille && <span>· {org.taille} salariés</span>}
          {org.secteur_activite && (
            <span className="truncate">· {org.secteur_activite}</span>
          )}
        </div>

        <div className="flex items-center gap-4 text-xs text-muted-foreground border-t pt-3">
          <div className="flex items-center gap-1.5">
            <Users className="h-3.5 w-3.5" />
            <span>
              {memberCount === null ? "…" : `${memberCount} membre${memberCount > 1 ? "s" : ""}`}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" />
            <span>
              {docCount === null ? "…" : `${docCount} document${docCount > 1 ? "s" : ""}`}
            </span>
          </div>
        </div>

        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={(e) => {
            e.stopPropagation();
            onClick();
          }}
        >
          Gérer
        </Button>
      </CardContent>
    </Card>
  );
}

