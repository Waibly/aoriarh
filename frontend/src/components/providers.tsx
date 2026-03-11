"use client";

import { SessionProvider } from "next-auth/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { OrgProvider } from "@/lib/org-context";
import { SessionGuard } from "@/components/session-guard";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={14 * 60}>
      <SessionGuard>
        <OrgProvider>
          <TooltipProvider>{children}</TooltipProvider>
        </OrgProvider>
      </SessionGuard>
    </SessionProvider>
  );
}
