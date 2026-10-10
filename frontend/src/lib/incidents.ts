"use client";

type IncidentCode = "ui_error" | "react_error" | "stream_error" | "stream_incomplete" | "stream_parse_error" | "turnstile_error" | "turnstile_timeout" | "request_timeout";
export type IncidentReason = "provider_quota_exhausted" | "provider_rate_limited" | "server_error";
export type IncidentOptions = { request_id?: string | null; id?: string; reason?: IncidentReason };

/** Protocol codes only: no error messages or generated text enter telemetry. */
export function incidentReason(value: unknown): IncidentReason | undefined {
  return value === "provider_quota_exhausted" || value === "provider_rate_limited" || value === "server_error"
    ? value : undefined;
}

declare global {
  interface Window {
    aoriaReportIncident?: (code: IncidentCode, options?: IncidentOptions) => void;
  }
}

export function reportIncident(code: IncidentCode, options?: IncidentOptions) {
  if (typeof window !== "undefined") {
    try { window.aoriaReportIncident?.(code, options); } catch { /* Never change product behavior. */ }
  }
}
