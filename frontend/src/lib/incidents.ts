"use client";

type IncidentCode = "ui_error" | "react_error" | "stream_error" | "stream_incomplete" | "stream_parse_error" | "turnstile_error" | "turnstile_timeout" | "request_timeout";
declare global {
  interface Window {
    aoriaReportIncident?: (code: IncidentCode, options?: { request_id?: string | null; id?: string }) => void;
  }
}

export function reportIncident(code: IncidentCode, options?: { request_id?: string | null; id?: string }) {
  if (typeof window !== "undefined") {
    try { window.aoriaReportIncident?.(code, options); } catch { /* Never change product behavior. */ }
  }
}
