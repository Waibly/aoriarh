import type { Instrumentation } from "next";

export const onRequestError: Instrumentation.onRequestError = async (_error, _request, context) => {
  if (process.env.NODE_ENV !== "production") return;
  try {
    const response = await fetch(`${process.env.INTERNAL_API_URL || "http://backend:8000/api/v1"}/telemetry/incidents`, {
      method: "POST", headers: { "Content-Type": "application/json", Origin: "https://app.aoriarh.fr" },
      body: JSON.stringify({id: crypto.randomUUID(), source: "nextjs", code: "server_render_error", location: context.routePath}),
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) console.error("aoria_server_incident_delivery_failed");
  } catch { console.error("aoria_server_incident_delivery_failed"); }
};
