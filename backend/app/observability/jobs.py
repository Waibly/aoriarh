"""Observe ARQ jobs without changing retries, results or exceptions."""

import asyncio
import functools
import time
import uuid

from app.observability.store import capture, context, set_state


def observed_job(function):
    @functools.wraps(function)
    async def observed(ctx, *args, **kwargs):
        job_id = str(ctx.get("job_id") or uuid.uuid4())
        name = function.__name__
        fields = {
            "source": "worker",
            "job_id": job_id,
            "job_name": name,
            "incident_key": "job:" + job_id,
        }
        if name == "run_ingestion" and args:
            fields["document_id"] = str(args[0])
        token = context.set(fields)
        started = time.time()

        def state(status):
            try:
                set_state(
                    "job:" + job_id,
                    {"name": name, "started": started, "updated": time.time(), "status": status},
                )
                set_state("schedule:" + name, {"started": started, "status": status})
            except Exception:
                capture("job_tracking_failed")

        state("running")
        try:
            result = await function(ctx, *args, **kwargs)
            state("finished")
            return result
        except asyncio.CancelledError:
            capture("job_cancelled")
            state("cancelled")
            raise
        except Exception as exc:
            capture("job_failed", exception_type=type(exc).__name__)
            state("failed")
            raise
        finally:
            context.reset(token)

    return observed


def track_queue(pool):
    original = pool.enqueue_job

    async def enqueue(name, *args, **kwargs):
        try:
            job = await original(name, *args, **kwargs)
        except Exception as exc:
            capture("job_enqueue_failed", job_name=name, exception_type=type(exc).__name__)
            raise
        if job is not None:
            try:
                # Do not replace running state if a fast worker has already claimed it.
                import json

                from app.observability.store import connection, enabled

                if enabled():
                    with connection() as db:
                        db.execute(
                            "INSERT OR IGNORE INTO state(key,value) VALUES(?,?)",
                            (
                                "job:" + job.job_id,
                                json.dumps(
                                    {
                                        "name": name,
                                        "started": time.time(),
                                        "updated": time.time(),
                                        "status": "queued",
                                    }
                                ),
                            ),
                        )
            except Exception:
                capture("job_tracking_failed", job_name=name)
        return job

    pool.enqueue_job = enqueue


async def heartbeat():
    while True:
        try:
            await asyncio.to_thread(set_state, "worker_heartbeat", time.time())
        except Exception:
            capture("worker_heartbeat_failed")
        await asyncio.sleep(15)
