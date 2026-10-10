"""Durable local outbox, independent of Postgres/Redis and business rollbacks.

Only allowlisted metadata is persisted. No message, body, URL query, exception
text or stack locals. SQLite WAL supports API processes and the separate worker.
"""

import contextvars
import json
import logging
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager

context = contextvars.ContextVar("incident_context", default=None)
FIELDS = {
    "source",
    "reason",
    "code",
    "request_id",
    "job_id",
    "job_name",
    "document_id",
    "user_id",
    "organisation_id",
    "sync_id",
    "sync_type",
    "status",
    "location",
    "exception_type",
    "line",
    "items_failed",
    "release",
    "visitor_id",
    "method",
}
SAFE = re.compile(r"^[a-zA-Z0-9_./:{}@\[\]()-]{1,180}$")


def enabled():
    return bool(os.environ.get("INCIDENT_DB"))


@contextmanager
def connection():
    path = os.environ["INCIDENT_DB"]
    db = sqlite3.connect(path, timeout=0.5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript("""
          CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, delivered REAL, last_error TEXT);
          CREATE INDEX IF NOT EXISTS incidents_pending ON incidents(state,next_attempt);
          CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        yield db
        db.commit()
    finally:
        db.close()


def clean(data):
    result = {}
    for key, value in data.items():
        if key not in FIELDS or value is None:
            continue
        if isinstance(value, int):
            result[key] = value
        elif isinstance(value, str) and SAFE.fullmatch(value):
            result[key] = value
    return result


def identifier(key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "aoriarh-incident:" + key))


def capture(code, *, key=None, **fields):
    if not enabled():
        return None
    current = context.get() or {}
    data = clean(
        {**current, **fields, "code": code, "release": os.environ.get("APP_RELEASE", "unknown")}
    )
    # One request/job error seen at multiple layers remains one incident.
    event_id = identifier(key or current.get("incident_key") or str(uuid.uuid4()))
    try:
        with connection() as db:
            existing = db.execute(
                "SELECT payload FROM incidents WHERE id=?", (event_id,)
            ).fetchone()
            if existing:
                previous = json.loads(existing["payload"])
                # Enrich without erasing the original diagnostic category.
                data = {**data, **previous}
                if fields.get("status"):
                    data["status"] = fields["status"]
                db.execute(
                    "UPDATE incidents SET payload=? WHERE id=?", (json.dumps(data), event_id)
                )
            else:
                db.execute(
                    "INSERT INTO incidents(id,created,payload) VALUES(?,?,?)",
                    (event_id, time.time(), json.dumps(data)),
                )
        return event_id
    except Exception:
        # No recursion through logging and no potentially sensitive exception text.
        sys.stderr.write("aoria_incident_persistence_failed\n")
        return None


def set_state(key, value):
    if enabled():
        with connection() as db:
            db.execute("INSERT OR REPLACE INTO state VALUES(?,?)", (key, json.dumps(value)))


def get_state(key, default=None):
    with connection() as db:
        row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


class IncidentLogHandler(logging.Handler):
    """Catch technical ERROR logs, without copying their formatted message."""

    def emit(self, record):
        if not enabled() or record.name.startswith("app.observability"):
            return
        fields = {
            "source": os.environ.get("INCIDENT_SOURCE", "backend"),
            "location": record.name,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            fields["exception_type"] = record.exc_info[0].__name__
        capture("python_error", **fields)
