"use client";

import { Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/**
 * Small info icon that displays an explanation on hover.
 * Use this to make admin metrics and controls self-documenting
 * without cluttering the UI.
 */
export function InfoTooltip({
  children,
  side = "top",
  className = "",
}: {
  children: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
}) {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger
          type="button"
          className={`inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors ${className}`}
          aria-label="Information"
        >
          <Info className="h-3 w-3" />
        </TooltipTrigger>
        <TooltipContent
          side={side}
          className="max-w-xs text-xs leading-relaxed bg-popover text-popover-foreground border shadow-md p-2"
        >
          {children}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
