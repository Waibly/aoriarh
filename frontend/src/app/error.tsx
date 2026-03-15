"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Application error:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6">
      <div className="flex size-16 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="size-8 text-destructive" />
      </div>
      <h2 className="text-lg font-semibold">
        Un problème est survenu
      </h2>
      <p className="max-w-md text-center text-sm text-muted-foreground">
        L&apos;application a rencontré une erreur inattendue.
        Veuillez recharger la page.
      </p>
      <div className="flex gap-3">
        <Button onClick={reset} variant="outline">
          Réessayer
        </Button>
        <Button onClick={() => (window.location.href = "/chat")}>
          Retour au chat
        </Button>
      </div>
    </div>
  );
}
