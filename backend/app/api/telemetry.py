"""Public, bounded metadata collector. No free text or user-supplied identity."""

import json
import time
import uuid
from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.dependencies import require_role
from app.observability.store import capture, connection, enabled, get_state

router = APIRouter()
ORIGINS = {"https://aoriarh.fr", "https://www.aoriarh.fr", "https://app.aoriarh.fr"}
_buckets = OrderedDict()


class IncidentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    source: Literal["site", "app", "nextjs"]
    code: Literal[
        "javascript_error",
        "unhandled_rejection",
        "resource_error",
        "http_error",
        "network_error",
        "request_timeout",
        "react_error",
        "ui_error",
        "stream_error",
        "stream_incomplete",
        "stream_parse_error",
        "turnstile_error",
        "turnstile_timeout",
        "form_invalid",
        "server_render_error",
    ]
    location: str = Field(
        default="unknown", max_length=180, pattern=r"^[a-zA-Z0-9_./:{}@\[\]()-]+$"
    )
    request_id: uuid.UUID | None = None
    visitor_id: uuid.UUID | None = None
    status: int | None = Field(default=None, ge=400, le=599)


def allow_client(ip):
    now = time.monotonic()
    start, count = _buckets.get(ip, (now, 0))
    if now - start > 60:
        start, count = now, 0
    _buckets[ip] = (start, count + 1)
    _buckets.move_to_end(ip)
    while len(_buckets) > 10000:
        _buckets.popitem(last=False)
    return count < 120


@router.post("/incidents", status_code=202)
async def receive_incident(request: Request):
    if request.headers.get("origin") not in ORIGINS:
        raise HTTPException(403, "Origin not allowed")
    if not allow_client(request.client.host if request.client else "unknown"):
        raise HTTPException(429, "Telemetry rate limit", headers={"Retry-After": "60"})
    size = 0
    parts = []
    async for part in request.stream():
        size += len(part)
        if size > 2048:
            raise HTTPException(413, "Metadata too large")
        parts.append(part)
    try:
        incident = IncidentInput.model_validate_json(b"".join(parts))
    except ValidationError:
        raise HTTPException(422, "Invalid incident metadata") from None
    if not enabled():
        raise HTTPException(503, "Incident collector not configured")
    data = incident.model_dump(mode="json", exclude_none=True)
    key = (
        "request:" + str(incident.request_id)
        if incident.request_id
        else "browser:" + str(incident.id)
    )
    event_id = capture(data.pop("code"), key=key, **{k: v for k, v in data.items() if k != "id"})
    if event_id is None:
        raise HTTPException(503, "Incident persistence unavailable")
    return {"incident_id": event_id}


# Separate authenticated operations; public reports never choose trusted user IDs.


@router.get("/admin/incidents")
async def list_incidents(
    state: Literal["pending", "failed", "delivered"] | None = None,
    offset: int = Query(default=0, ge=0),
    _user=Depends(require_role(["admin"])),
):
    if not enabled():
        return {"configured": False, "items": [], "counts": {}}
    with connection() as db:
        where, args = (" WHERE state=?", [state]) if state else ("", [])
        rows = db.execute(
            "SELECT * FROM incidents" + where + " ORDER BY created DESC LIMIT 100 OFFSET ?",
            [*args, offset],
        ).fetchall()
        counts = {
            r[0]: r[1] for r in db.execute("SELECT state,count(*) FROM incidents GROUP BY state")
        }
    return {
        "configured": True,
        "counts": counts,
        "last_delivery": get_state("slack_last_result"),
        "items": [{**dict(r), "payload": json.loads(r["payload"])} for r in rows],
    }


@router.post("/admin/incidents/{incident_id}/retry")
async def retry_incident(incident_id: uuid.UUID, _user=Depends(require_role(["admin"]))):
    with connection() as db:
        result = db.execute(
            "UPDATE incidents SET "
            "state='pending',attempts=0,next_attempt=0,last_error=NULL WHERE "
            "id=? AND state='failed'",
            (str(incident_id),),
        )
    if not result.rowcount:
        raise HTTPException(409, "Incident absent ou non en échec de livraison")
    return {"queued": True}


@router.get("/health")
async def delivery_health():
    """No incident details. Used by an external monitor when local monitoring dies."""
    if not enabled():
        return Response(status_code=503)
    try:
        with connection() as db:
            oldest = db.execute(
                "SELECT min(created) FROM incidents WHERE state='pending'"
            ).fetchone()[0]
            failed = db.execute("SELECT count(*) FROM incidents WHERE state='failed'").fetchone()[0]
        now = time.time()
        healthy = (
            get_state("slack_configured", False)
            and now - get_state("notifier_tick", 0) < 60
            and now - get_state("watchdog_ok", 0) < 180
            and now - get_state("worker_heartbeat", 0) < 90
            and not failed
            and (oldest is None or now - oldest < 120)
        )
        return Response(status_code=200 if healthy else 503)
    except Exception:
        return Response(status_code=503)
