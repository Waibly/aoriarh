"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession } from "next-auth/react";
import { Loader2, AlertTriangle } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useOrg } from "@/lib/org-context";
import type { OrganisationConvention } from "@/types/api";

const PENDING_STATUSES: ReadonlyArray<OrganisationConvention["status"]> = [
  "pending",
  "fetching",
  "indexing",
];

/**
 * Cross-page banner that warns the user as long as one of their installed
 * CCNs has not finished syncing from KALI. Hides itself once everything is
 * `ready` (or `error`, in which case the user is sent to /documents to retry).
 *
 * Polls every 5 s while a sync is in progress, then stops polling.
 */
export function CcnInstallBanner() {
  const { data: session } = useSession();
  const { currentOrg } = useOrg();
  const pathname = usePathname();
  const [conventions, setConventions] = useState<OrganisationConvention[]>([]);

  const token = session?.access_token;
  const orgId = currentOrg?.id;

  useEffect(() => {
    if (!token || !orgId) return;
    let cancelled = false;
    let pollId: ReturnType<typeof setInterval> | null = null;

    const load = async () => {
      try {
        const data = await apiFetch<OrganisationConvention[]>(
          `/conventions/organisations/${orgId}`,
          { token },
        );
        if (cancelled) return;
        setConventions(data);
        const stillPending = data.some((c) =>
          PENDING_STATUSES.includes(c.status),
        );
        if (!stillPending && pollId) {
          clearInterval(pollId);
          pollId = null;
        }
      } catch {
        // Silent — banner just doesn't render.
      }
    };

    load();
    pollId = setInterval(load, 5000);
    return () => {
      cancelled = true;
      if (pollId) clearInterval(pollId);
    };
  }, [token, orgId]);

  const pending = useMemo(
    () => conventions.filter((c) => PENDING_STATUSES.includes(c.status)),
    [conventions],
  );
  const errored = useMemo(
    () => conventions.filter((c) => c.status === "error"),
    [conventions],
  );

  // Don't double up the message on /documents (the CCN section already
  // shows progress + error states inline).
  const onDocuments = pathname?.startsWith("/documents") ?? false;

  if (onDocuments) return null;
  if (pending.length === 0 && errored.length === 0) return null;

  if (errored.length > 0) {
    return (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4 border-b border-destructive/30 bg-destructive/10 px-4 py-3 text-sm sm:px-6 text-destructive">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            L&apos;installation de votre convention collective a échoué.
            Réessayez depuis la page Documents.
          </span>
        </div>
        <Link
          href="/documents"
          className="font-medium underline underline-offset-2 self-start sm:self-auto"
        >
          Aller à Documents
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4 border-b border-orange-200 dark:border-orange-900 bg-orange-50 dark:bg-orange-950/30 px-4 py-3 text-sm sm:px-6 text-orange-800 dark:text-orange-200">
      <div className="flex items-center gap-2">
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
        <span>
          Votre convention collective est en cours d&apos;installation.
          AORIA RH peut déjà répondre depuis le Code du travail, mais
          l&apos;appui sur votre CCN sera disponible d&apos;ici 1-2 minutes.
        </span>
      </div>
      <Link
        href="/documents"
        className="font-medium underline underline-offset-2 self-start sm:self-auto"
      >
        Voir l&apos;avancement
      </Link>
    </div>
  );
}
