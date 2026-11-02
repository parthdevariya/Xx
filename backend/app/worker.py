"""Background worker: claims jobs from background_jobs and runs them.

    python -m app.worker            # standalone worker process (Render background worker)

The API can also run an embedded worker thread (X_EMBEDDED_WORKER=true) for single-process deployments.
Claiming uses a conditional UPDATE (status='queued' → 'running'), which is atomic on PostgreSQL and SQLite,
so several workers can poll the same table safely.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import timedelta

from sqlalchemy import select, update

from .db import SessionLocal
from .models import BackgroundJob, Execution, utcnow

log = logging.getLogger("x.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
STALE_AFTER = timedelta(minutes=20)


def claim_next(db) -> BackgroundJob | None:
    candidates = db.scalars(select(BackgroundJob.id).where(BackgroundJob.status == "queued",
                                                           BackgroundJob.run_after <= utcnow())
                            .order_by(BackgroundJob.created_at).limit(5)).all()
    for job_id in candidates:
        res = db.execute(update(BackgroundJob)
                         .where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
                         .values(status="running", locked_by=WORKER_ID, locked_at=utcnow(), heartbeat_at=utcnow(),
                                 attempts=BackgroundJob.attempts + 1))
        db.commit()
        if res.rowcount == 1:
            return db.get(BackgroundJob, job_id)
    return None


def recover_stale(db) -> int:
    """Fail jobs whose worker died mid-run, and their executions, with a visible reason."""
    cutoff = utcnow() - STALE_AFTER
    stale = db.scalars(select(BackgroundJob).where(BackgroundJob.status == "running",
                                                   BackgroundJob.heartbeat_at < cutoff)).all()
    from .orchestration.events import emit
    for job in stale:
        job.status, job.error, job.finished_at = "failed", "worker lost (no heartbeat)", utcnow()
        if job.execution_id:
            ex = db.get(Execution, job.execution_id)
            if ex and ex.status in ("queued", "running"):
                ex.status, ex.error = "failed", "worker lost during execution; resubmit to retry"
                emit(db, ex, "system", "execution.failed", "Execution failed: worker lost during execution", {},
                     commit=False)
    db.commit()
    return len(stale)


def run_job(job_id: str) -> None:
    from .orchestration.executor import run_execution
    db = SessionLocal()
    try:
        job = db.get(BackgroundJob, job_id)
        payload = dict(job.payload)
        result = None
        if job.kind == "execution":
            run_execution(db, payload["execution_id"])
        elif job.kind == "intellect_regression":
            from .intellect.lab import run_regression
            result = run_regression(db, payload["framework_id"], payload["version_id"], payload.get("user_id"))
        elif job.kind == "intellect_lab":
            from .intellect.lab import run_lab_job
            result = run_lab_job(db, payload)
        job = db.get(BackgroundJob, job_id)
        if result is not None:
            job.payload = {**payload, "result": result}
        job.status, job.finished_at = "done", utcnow()
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("job %s failed", job_id)
        db.rollback()
        job = db.get(BackgroundJob, job_id)
        job.status, job.error, job.finished_at = "failed", str(e)[:4000], utcnow()
        db.commit()
    finally:
        db.close()


def work_once() -> bool:
    db = SessionLocal()
    try:
        job = claim_next(db)
        job_id = job.id if job else None
    finally:
        db.close()
    if job_id:
        run_job(job_id)
        return True
    return False


def loop(stop: threading.Event | None = None, idle_sleep: float = 1.0) -> None:
    db = SessionLocal()
    try:
        n = recover_stale(db)
        if n:
            log.warning("recovered %d stale job(s)", n)
    finally:
        db.close()
    log.info("worker %s started", WORKER_ID)
    while not (stop and stop.is_set()):
        try:
            if not work_once():
                time.sleep(idle_sleep)
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            time.sleep(5)


_thread: threading.Thread | None = None
_stop = threading.Event()


def start_embedded() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=loop, args=(_stop,), name="x-embedded-worker", daemon=True)
    _thread.start()


def stop_embedded() -> None:
    _stop.set()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from .bootstrap import bootstrap
    # The API service runs migrations; on a fresh deploy the worker waits until the schema exists.
    for attempt in range(30):
        try:
            bootstrap(migrate=False)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("database not ready (%s); retrying in 5s", str(e).splitlines()[0][:200])
            time.sleep(5)
    else:
        raise SystemExit("database never became ready")
    loop()
