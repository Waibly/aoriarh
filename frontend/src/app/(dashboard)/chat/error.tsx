"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ChatError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Chat error:", error);
  }, [error]);

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
      <div className="flex size-16 items-center justify-center rounded-full bg-destructive/10">
        <AlertTriangle className="size-8 text-destructive" />
      </div>
      <h2 className="text-lg font-semibold text-foreground">
        Erreur dans le chat
      </h2>
      <p className="max-w-md text-center text-sm text-muted-foreground">
        La conversation a rencontré un problème. Vos messages ne sont pas
        perdus.
      </p>
      <Button onClick={reset} variant="outline" className="gap-2">
        <RefreshCw className="size-4" />
        Relancer le chat
      </Button>
    </div>
  );
}
