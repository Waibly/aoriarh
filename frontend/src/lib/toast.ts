"use client";
import { toast as original } from "sonner";
import { reportIncident } from "@/lib/incidents";

// Keep Sonner's callable API, methods and options. Do not copy error text.
export const toast = Object.assign(
  (...args: Parameters<typeof original>) => original(...args),
  original,
  { error: (...args: Parameters<typeof original.error>) => {
    reportIncident("ui_error");
    return original.error(...args);
  } },
);
