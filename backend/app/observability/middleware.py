"""ASGI observation including exceptions and streaming, without reading bodies."""

import uuid

from app.observability.store import capture, context


class IncidentMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in {
            "/health",
            "/metrics",
            "/api/v1/telemetry/incidents",
            "/api/v1/telemetry/health",
        }:
            return await self.app(scope, receive, send)
        request_id = str(uuid.uuid4())
        fields = {
            "request_id": request_id,
            "incident_key": "request:" + request_id,
            "source": "backend",
            "method": scope["method"],
        }
        token = context.set(fields)
        scope.setdefault("state", {})["request_id"] = request_id

        async def observed_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
                route = scope.get("route")
                # Route templates exclude user input and tokens in URL parameters.
                fields["location"] = getattr(route, "path", "unmatched_route")
                if message["status"] >= 400:
                    headers = dict(scope.get("headers", []))
                    # Existing unauthenticated contract probe expects this exact 403.
                    probe = headers.get(b"user-agent", b"").startswith(b"Aoria-Technical-Monitor/")
                    if not (
                        probe and scope["path"] == "/api/v1/public/ask" and message["status"] == 403
                    ):
                        capture("http_error", status=message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as exc:
            capture("unhandled_exception", exception_type=type(exc).__name__, status=500)
            raise
        finally:
            context.reset(token)
