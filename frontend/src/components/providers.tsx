"use client";

import { SessionProvider } from "next-auth/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { OrgProvider } from "@/lib/org-context";
import { SessionGuard } from "@/components/session-guard";
import { MobileViewport } from "@/components/mobile-viewport";
import { SupportWidget } from "@/components/support-widget";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider refetchInterval={5 * 60} refetchOnWindowFocus>
      <SessionGuard>
        <OrgProvider>
          <TooltipProvider>
            <MobileViewport />
            {children}
            <SupportWidget />
          </TooltipProvider>
        </OrgProvider>
      </SessionGuard>
    </SessionProvider>
  );
}
