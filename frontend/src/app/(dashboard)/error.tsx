"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard error:", error);
  }, [error]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
      <div className="flex size-16 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="size-8 text-destructive" />
      </div>
      <h2 className="text-lg font-semibold text-foreground">
        Une erreur est survenue
      </h2>
      <p className="max-w-md text-center text-sm text-muted-foreground">
        Un problème inattendu s&apos;est produit. Vous pouvez essayer de
        recharger cette section.
      </p>
      <Button onClick={reset} variant="outline">
        Recharger
      </Button>
    </div>
  );
}
