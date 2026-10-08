"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getDossier, type DossierDetail } from "@/lib/dossiers-api";
import { DossierContent } from "./dossier-content";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";

export function DossierPanel({
  id,
  token,
  open,
  onOpenChange,
  refreshVersion,
}: {
  id: string;
  token: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  refreshVersion: number;
}) {
  const [d, setD] = useState<DossierDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"informations" | "documents">("informations");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    if (!open) return;
    setError("");
    setD((current) => (current?.id === id ? current : null));
    void getDossier(id, token)
      .then((r) => {
        if (!cancelled) setD(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [id, token, open, refreshVersion, retry]);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-xl">
        <SheetHeader className="border-b p-5 pr-12">
          <SheetTitle>{d?.name || "Dossier"}</SheetTitle>
          <SheetDescription>
            Informations et documents communs aux conversations de ce dossier.
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-5 p-5">
          {error && (
            <div role="alert">
              {error}
              <Button variant="outline" onClick={() => setRetry((v) => v + 1)}>
                Réessayer
              </Button>
            </div>
          )}
          {!d ? (
            <p role="status">Chargement…</p>
          ) : (
            <>
              <Link href={`/dossiers/${id}`} className="text-primary text-sm">
                Ouvrir le dossier et ses conversations →
              </Link>
              <div
                className="flex gap-2"
                role="tablist"
                aria-label="Contenu du dossier"
              >
                <Button
                  role="tab"
                  variant="ghost"
                  className={
                    tab === "informations"
                      ? "bg-accent text-primary"
                      : "text-muted-foreground"
                  }
                  aria-selected={tab === "informations"}
                  onClick={() => setTab("informations")}
                >
                  Informations
                </Button>
                <Button
                  role="tab"
                  variant="ghost"
                  className={
                    tab === "documents"
                      ? "bg-accent text-primary"
                      : "text-muted-foreground"
                  }
                  aria-selected={tab === "documents"}
                  onClick={() => setTab("documents")}
                >
                  Documents
                </Button>
              </div>
              <DossierContent
                key={d.id}
                dossier={d}
                token={token}
                tab={tab}
                onChange={setD}
              />
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
