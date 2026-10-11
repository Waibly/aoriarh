"""Single durable Slack dispatcher + independent documentary watchdog.

Run separately from ARQ: python -m app.observability.notifier.
No business operation or LLM call is retried here.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx

from app.observability.store import capture, connection, get_state, set_state

MAX_ATTEMPTS = 8
GROUP_INTERVAL = 60
MAX_BATCH = 1000
# Stable technical fields only. Identities remain on individual incident records.
GROUP_FIELDS = (
    "source", "code", "reason", "location", "status", "method", "exception_type",
    "job_name", "sync_type", "release",
)
GROUP_SQL = "json_array(" + ",".join(
    f"json_extract(i.payload, '$.{field}')" for field in GROUP_FIELDS
) + ")"


def slack_message(row, batch=None):
    data = json.loads(row["payload"])
    labels = {
        "provider_quota_exhausted": "Crédits OpenAI épuisés",
        "provider_rate_limited": "Limite de débit du service IA atteinte",
        "server_error": "Erreur technique du service IA",
    }
    cause = labels.get(data.get("reason"))
    title = "AORIA RH — " + cause if cause else "AORIA RH — incident de production"
    lines = [
        title,
        "Incident : " + row["id"],
        "Date UTC : " + datetime.fromtimestamp(row["created"], UTC).isoformat(),
    ]
    if batch and len(batch) > 1:
        lines += [
            f"Occurrences regroupées : {len(batch)}",
            "Dernière occurrence UTC : "
            + datetime.fromtimestamp(batch[-1]["created"], UTC).isoformat(),
            "Détail ci-dessous : premier incident du groupe.",
            "Chaque occurrence reste consultable individuellement dans l’administration.",
        ]
    lines += [f"{key} : {value}" for key, value in data.items()]
    lines.append("Suivi : https://app.aoriarh.fr/admin/incidents")
    # plain_text prevents mentions, links or formatting supplied by a public client.
    return {
        "text": title + " — incident " + row["id"],
        "blocks": [{"type": "section", "text": {"type": "plain_text", "text": "\n".join(lines)}}],
    }


def exclude_site_incidents():
    """Retain historical records, but never send/retry marketing-site incidents."""
    with connection() as db:
        db.execute(
            "UPDATE incidents SET state='ignored',last_error='site_notifications_disabled' "
            "WHERE state IN ('pending','failed') AND json_extract(payload, '$.source')='site'"
        )


async def deliver_one(client, webhook):
    exclude_site_incidents()
    now = time.time()
    if now < get_state("slack_backoff", 0):
        return False
    with connection() as db:
        # A cooldown suppresses repeated Slack messages, never incident collection.
        # SQL skips cooling groups so another category is not blocked behind them.
        row = db.execute(
            "SELECT i.*, " + GROUP_SQL + " AS group_key FROM incidents i "
            "LEFT JOIN state s ON s.key='slack_group:' || " + GROUP_SQL + " "
            "WHERE i.state='pending' AND i.next_attempt<=? AND i.created<=? "
            "AND COALESCE(json_extract(i.payload, '$.source'), '') != 'site' "
            "AND COALESCE(CAST(s.value AS REAL),0)<=? ORDER BY i.created LIMIT 1",
            (now, now - 2, now),
        ).fetchone()
        if row is None:
            return False
        batch = db.execute(
            "SELECT i.* FROM incidents i WHERE i.state='pending' "
            "AND i.next_attempt<=? AND i.created<=? AND " + GROUP_SQL + "=? "
            "ORDER BY i.created LIMIT ?",
            (now, now - 2, row["group_key"], MAX_BATCH),
        ).fetchall()
    try:
        response = await client.post(webhook, json=slack_message(row, batch))
        success = response.status_code == 200 and response.text.strip() == "ok"
        retryable = response.status_code == 429 or response.status_code >= 500
        error = "http_" + str(response.status_code)
        try:
            delay = max(1, min(int(response.headers.get("Retry-After", "0")), 86400))
        except ValueError:
            delay = 1
        if response.status_code == 429:
            set_state("slack_backoff", now + delay)
    except (httpx.TransportError, httpx.TimeoutException):
        success, retryable, error, delay = False, True, "transport_error", 0
    with connection() as db:
        for incident in batch:
            attempts = incident["attempts"] + 1
            state = (
                "delivered" if success
                else ("pending" if retryable and attempts < MAX_ATTEMPTS else "failed")
            )
            db.execute(
                "UPDATE incidents SET "
                "state=?,attempts=?,next_attempt=?,delivered=?,last_error=? WHERE id=?",
                (
                    state, attempts,
                    now + max(delay, min(3600, 15 * 2 ** (attempts - 1))),
                    now if success else None, None if success else error, incident["id"],
                ),
            )
        if success:
            db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?)",
                ("slack_group:" + row["group_key"], json.dumps(time.time() + GROUP_INTERVAL)),
            )
    set_state(
        "slack_last_result", {"at": now, "success": success, "error": None if success else error}
    )
    return True


async def documentary_watchdog():
    """Read committed states, including errors swallowed by service functions."""
    import asyncpg

    since = get_state("watchdog_cursor", time.time())
    now = time.time()
    db = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
        timeout=5,
        command_timeout=10,
    )
    try:
        # Overlap prevents transaction/scan races. Stable keys prevent repeat delivery.
        cutoff = datetime.fromtimestamp(since - 300, UTC)
        activated = datetime.fromtimestamp(get_state("activated_at", now), UTC)
        if not get_state("documentary_baseline"):
            for code, query in [
                (
                    "existing_document_errors",
                    "SELECT count(*) FROM documents WHERE retired_at IS NULL AND "
                    "indexation_status='error' AND updated_at<=$1",
                ),
                (
                    "existing_stalled_documents",
                    "SELECT count(*) FROM documents WHERE retired_at IS NULL AND "
                    "indexation_status IN ('pending','indexing') AND updated_at<=$1 AND "
                    "updated_at<now()-interval '5 hours'",
                ),
                (
                    "existing_stalled_syncs",
                    "SELECT count(*) FROM sync_logs WHERE status='running' AND "
                    "started_at<=$1 AND started_at<now()-interval '5 hours'",
                ),
            ]:
                count = await db.fetchval(query, activated)
                if count:
                    capture(code, key="baseline:" + code, source="watchdog", items_failed=count)
            set_state("documentary_baseline", True)
        for row in await db.fetch(
            """SELECT id,sync_type,errors,completed_at,started_at FROM sync_logs
            WHERE (status='error' OR errors>0) AND COALESCE(completed_at,started_at)>$1""",
            cutoff,
        ):
            version = str(row["completed_at"] or row["started_at"])
            capture(
                "sync_result_failed",
                key=f"sync:{row['id']}:{version}:{row['errors']}",
                source="watchdog",
                sync_id=str(row["id"]),
                sync_type=row["sync_type"],
                items_failed=row["errors"],
            )
        for row in await db.fetch(
            """SELECT id,organisation_id,updated_at,indexation_status FROM documents
            WHERE retired_at IS NULL AND ((indexation_status='error' AND updated_at>$1)
              OR (indexation_status IN ('pending','indexing') AND updated_at > $2
              AND updated_at < now()-interval '5 hours'))""",
            cutoff,
            activated,
        ):
            capture(
                "document_" + ("failed" if row["indexation_status"] == "error" else "stalled"),
                key=f"document:{row['id']}:{row['updated_at']}",
                source="watchdog",
                document_id=str(row["id"]),
                organisation_id=str(row["organisation_id"]) if row["organisation_id"] else None,
            )
        for row in await db.fetch(
            "SELECT id,sync_type FROM sync_logs WHERE status='running' AND "
            "started_at > $1 AND started_at < now()-interval '5 hours'",
            activated,
        ):
            capture(
                "sync_stalled",
                key="sync-stalled:" + str(row["id"]),
                source="watchdog",
                sync_id=str(row["id"]),
                sync_type=row["sync_type"],
            )
        set_state("watchdog_cursor", now)
        set_state("watchdog_ok", now)
    finally:
        await db.close()


# Mirrors active cron schedules, with a grace period for queue and restart delays.
SCHEDULES = {
    "run_storage_recovery": (None, None, None, 10),
    "run_legislation_sync": (5, 2, 0, None),
    "run_scheduled_sync": (6, 2, 0, None),
    "run_curated_sources_sync": (5, 6, 0, None),
    "run_social_ca_sync": (None, 7, 0, None),
    "run_daily_bocc_check": (None, 2, 30, None),
    "run_scheduled_boss_sync": (None, 5, 0, None),
    "run_billing_lifecycle": (None, 9, 0, None),
    "run_data_retention_purge": (None, 10, 0, None),
    "run_emailing_campaigns": (None, None, 0, 60),
    "run_jurisprudence_presence_check": ("monthly", 3, 0, None),
    "run_ani_sync": ("monthly", 4, 0, None),
}


def expected_start(now, schedule):
    weekday, hour, minute, interval = schedule
    if interval:
        stamp = int(now.timestamp()) // (interval * 60) * interval * 60
        return datetime.fromtimestamp(stamp, UTC)
    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if result > now:
        result -= timedelta(days=1)
    if weekday == "monthly":
        result = result.replace(day=1)
    elif weekday is not None:
        result -= timedelta(days=(result.weekday() - weekday) % 7)
    return result


def check_jobs():
    now = time.time()
    activated = get_state("activated_at", now)
    # Use a 20-minute grace period, then check the most recent due execution.
    clock = datetime.fromtimestamp(now - 1200, UTC)
    for name, schedule in SCHEDULES.items():
        due = expected_start(clock, schedule).timestamp()
        latest = get_state("schedule:" + name, {})
        if due > activated and latest.get("started", 0) < due:
            capture(
                "schedule_missing", key=f"schedule:{name}:{due}", source="watchdog", job_name=name
            )
    with connection() as db:
        jobs = db.execute("SELECT key,value FROM state WHERE key LIKE 'job:%'").fetchall()
    for row in jobs:
        job = json.loads(row["value"])
        if job["status"] == "queued" and now - job["started"] > 1800:
            capture(
                "job_queue_stalled",
                key=row["key"],
                source="watchdog",
                job_id=row["key"][4:],
                job_name=job["name"],
            )
        elif job["status"] == "running" and now - job["started"] > 4 * 3600 + 120:
            capture(
                "job_stalled",
                key=row["key"],
                source="watchdog",
                job_id=row["key"][4:],
                job_name=job["name"],
            )
        elif job["status"] not in {"running", "queued"} and now - job["updated"] > 7 * 86400:
            with connection() as db:
                db.execute("DELETE FROM state WHERE key=?", (row["key"],))


class Metrics(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        with connection() as db:
            counts = {
                r[0]: r[1]
                for r in db.execute("SELECT state,count(*) FROM incidents GROUP BY state")
            }
            oldest = db.execute(
                "SELECT min(created) FROM incidents WHERE state='pending'"
            ).fetchone()[0]
        values = {
            "pending": counts.get("pending", 0),
            "failed": counts.get("failed", 0),
            "oldest_pending_seconds": time.time() - oldest if oldest else 0,
            "loop_timestamp": get_state("notifier_tick", 0),
            "watchdog_timestamp": get_state("watchdog_ok", 0),
            "worker_timestamp": get_state("worker_heartbeat", 0),
            "slack_configured": int(bool(os.environ.get("AORIA_SLACK_WEBHOOK_URL"))),
        }
        body = "".join(f"aoria_incidents_{k} {v}\n" for k, v in values.items()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


async def main():
    exclude_site_incidents()
    if get_state("activated_at") is None:
        set_state("activated_at", time.time())
        set_state("watchdog_cursor", time.time())
    Thread(
        target=ThreadingHTTPServer(("0.0.0.0", 9117), Metrics).serve_forever, daemon=True
    ).start()
    webhook = os.environ.get("AORIA_SLACK_WEBHOOK_URL", "")
    if webhook and not webhook.startswith("https://hooks.slack.com/services/"):
        raise RuntimeError("Invalid Slack webhook host")
    set_state("slack_configured", bool(webhook))
    last_watch = 0
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        while True:
            try:
                set_state("notifier_tick", time.time())
                if time.time() - last_watch > 60:
                    last_watch = time.time()
                    try:
                        await documentary_watchdog()
                        check_jobs()
                    except Exception as exc:
                        capture(
                            "watchdog_failed",
                            key="watchdog:" + str(int(time.time() // 3600)),
                            source="notifier",
                            exception_type=type(exc).__name__,
                        )
                    with connection() as db:
                        db.execute(
                            "DELETE FROM incidents WHERE state='delivered' AND delivered<?",
                            (time.time() - 30 * 86400,),
                        )
                if webhook:
                    await deliver_one(client, webhook)
            except Exception:
                print("aoria_notifier_loop_failed", flush=True)
            await asyncio.sleep(1.1)


if __name__ == "__main__":
    asyncio.run(main())
