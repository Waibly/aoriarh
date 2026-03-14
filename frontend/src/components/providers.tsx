"use client";

import { SessionProvider } from "next-auth/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { OrgProvider } from "@/lib/org-context";
import { SessionGuard } from "@/components/session-guard";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={5 * 60} refetchOnWindowFocus>
      <SessionGuard>
        <OrgProvider>
          <TooltipProvider>{children}</TooltipProvider>
        </OrgProvider>
      </SessionGuard>
    </SessionProvider>
  );
}
