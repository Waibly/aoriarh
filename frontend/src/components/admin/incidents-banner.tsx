"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertOctagon, AlertTriangle, CheckCircle2, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export interface Incident {
  id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  detail: string | null;
  action_label: string;
  action_href: string;
}

// ----------------- Incident banner -----------------

const DISMISS_KEY = "aoria.dashboard.dismissed_incidents";

/** Compute a stable fingerprint for an incident so the dismissal
 *  re-appears automatically when the situation changes (e.g. error
 *  count goes from 3 to 5). */
function incidentFingerprint(inc: Incident): string {
  return `${inc.id}|${inc.title}|${inc.detail ?? ""}`;
}

function readDismissed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function writeDismissed(s: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DISMISS_KEY, JSON.stringify(Array.from(s)));
  } catch {
    // localStorage full / blocked — silent fallback, dismissal lasts only this session
  }
}

export function IncidentsBanner({ incidents }: { incidents: Incident[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  // Hydrate from localStorage on mount
  useEffect(() => {
    setDismissed(readDismissed());
  }, []);

  // Garbage-collect dismissals that no longer match any current incident
  // so we don't accumulate stale entries forever.
  useEffect(() => {
    if (dismissed.size === 0) return;
    const live = new Set(incidents.map(incidentFingerprint));
    const cleaned = new Set([...dismissed].filter((fp) => live.has(fp)));
    if (cleaned.size !== dismissed.size) {
      setDismissed(cleaned);
      writeDismissed(cleaned);
    }
  }, [incidents, dismissed]);

  const dismiss = (inc: Incident) => {
    const next = new Set(dismissed);
    next.add(incidentFingerprint(inc));
    setDismissed(next);
    writeDismissed(next);
  };

  const visible = incidents.filter(
    (inc) => !dismissed.has(incidentFingerprint(inc))
  );

  if (visible.length === 0) {
    return (
      <Card className="border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/30">
        <CardContent className="flex items-center gap-3 p-4">
          <CheckCircle2 className="text-muted-foreground h-5 w-5" />
          <div className="text-foreground text-sm font-medium">
            {incidents.length > 0
              ? `${incidents.length} alerte(s) masquée(s). Leur masquage ne résout pas les incidents.`
              : "Aucune alerte détectée par les indicateurs suivis."}
            {incidents.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                className="ml-3"
                onClick={() => {
                  setDismissed(new Set());
                  writeDismissed(new Set());
                }}
              >
                Réafficher
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <AlertOctagon className="h-4 w-4" />
          Incidents en cours ({visible.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {visible.map((inc) => {
          const colors =
            inc.severity === "critical"
              ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900 text-red-700 dark:text-red-300"
              : inc.severity === "warning"
                ? "bg-orange-50 dark:bg-orange-950/30 border-orange-200 dark:border-orange-900 text-orange-700 dark:text-orange-300"
                : "bg-blue-50 dark:bg-blue-950/30 border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300";
          const Icon =
            inc.severity === "critical" ? AlertOctagon : AlertTriangle;
          return (
            <div
              key={inc.id}
              className={`flex flex-wrap items-start gap-3 rounded-md border p-3 ${colors}`}
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0 flex-1 basis-full sm:basis-0">
                <div className="text-sm font-medium">{inc.title}</div>
                {inc.detail && (
                  <div className="mt-0.5 text-xs opacity-80">{inc.detail}</div>
                )}
              </div>
              <div className="ml-auto flex shrink-0 items-center gap-2 sm:ml-0">
                <Link href={inc.action_href}>
                  <Button size="sm" variant="outline" className="bg-background">
                    {inc.action_label}
                  </Button>
                </Link>
                <Button
                  size="icon"
                  variant="ghost"
                  className="hover:bg-background/60 h-7 w-7"
                  title="Masquer (réapparaît si la situation change)"
                  onClick={() => dismiss(inc)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
