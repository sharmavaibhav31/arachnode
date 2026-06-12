"""
main.py — APScheduler-based pipeline scheduler for the Job Discovery System.

Schedule:
  Every CRAWL_INTERVAL_HOURS   (default 8):
    → run_scrape_cycle()   POST /scrape + Scrapy subprocess

  Every DISCOVER_INTERVAL_HOURS (default 24, offset +4h from midnight):
    → run_discover_cycle() POST /discover for each new job

  Every DISCOVER_INTERVAL_HOURS (default 24, offset +8h from midnight):
    → run_draft_cycle()    POST /generate for jobs with contacts

After every cycle the run summary is flushed to /data/run_summary.json.
SIGTERM / SIGINT are handled gracefully — the scheduler stops accepting new
jobs and waits for the currently running job to finish.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

import tasks
from logger import get_logger

log = get_logger("scheduler.main")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CRAWL_INTERVAL_HOURS    = int(os.environ.get("CRAWL_INTERVAL_HOURS",    8))
DISCOVER_INTERVAL_HOURS = int(os.environ.get("DISCOVER_INTERVAL_HOURS", 24))
SUMMARY_PATH            = Path(os.environ.get("SUMMARY_PATH", "/data/run_summary.json"))

# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------

def _write_summary(extra: dict | None = None) -> None:
    """Flush the current task summary to SUMMARY_PATH."""
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        **tasks.get_summary(),
        **(extra or {}),
    }
    try:
        SUMMARY_PATH.write_text(json.dumps(data, indent=2))
        log.info("Run summary written", path=str(SUMMARY_PATH), data=data)
    except Exception as exc:
        log.error("Failed to write summary", error=str(exc))


# ---------------------------------------------------------------------------
# Wrapper that resets state, runs task, then flushes summary
# ---------------------------------------------------------------------------

_task_lock = threading.Lock()   # one task at a time


def _run(task_fn, task_name: str) -> None:
    if not _task_lock.acquire(blocking=False):
        log.warning("Another task is running — skipping", skipped=task_name)
        return
    try:
        log.info("Task starting", task=task_name)
        tasks.reset_summary()
        task_fn()
        _write_summary()
        log.info("Task complete", task=task_name)
    except Exception as exc:
        log.exception("Task raised an exception", task=task_name, error=str(exc))
        tasks._summary["errors"].append({"context": task_name, "detail": str(exc)})
        _write_summary()
    finally:
        _task_lock.release()


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_event = threading.Event()


def _handle_signal(signum, frame) -> None:
    sig_name = signal.Signals(signum).name
    log.info(f"Received {sig_name} — initiating graceful shutdown…")
    _shutdown_event.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def build_scheduler() -> BackgroundScheduler:
    executors = {"default": ThreadPoolExecutor(max_workers=1)}
    job_defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300}

    scheduler = BackgroundScheduler(
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )

    # ── Job 1: Scrape every CRAWL_INTERVAL_HOURS ──────────────────────────
    scheduler.add_job(
        func=lambda: _run(tasks.run_scrape_cycle, "scrape"),
        trigger="interval",
        hours=CRAWL_INTERVAL_HOURS,
        id="scrape",
        name="Platform + Scrapy scrape",
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
    )

    # ── Job 2: Discover contacts every DISCOVER_INTERVAL_HOURS ────────────
    scheduler.add_job(
        func=lambda: _run(tasks.run_discover_cycle, "discover"),
        trigger="interval",
        hours=DISCOVER_INTERVAL_HOURS,
        id="discover",
        name="Contact discovery",
        # offset by 4 hours so it doesn't overlap with the scrape job
        start_date=_offset_start(hours=4),
    )

    # ── Job 3: Pre-generate email drafts every DISCOVER_INTERVAL_HOURS ────
    scheduler.add_job(
        func=lambda: _run(tasks.run_draft_cycle, "draft"),
        trigger="interval",
        hours=DISCOVER_INTERVAL_HOURS,
        id="draft",
        name="Email draft pre-generation",
        # offset by 8 hours
        start_date=_offset_start(hours=8),
    )

    # ── Job 4: Weekly digest every Sunday at 09:00 UTC ────────────────────
    scheduler.add_job(
        func=lambda: _run(tasks.run_digest_cycle, "digest"),
        trigger="cron",
        day_of_week="sun",
        hour=9,
        minute=0,
        timezone="UTC",
        id="digest",
        name="Weekly job digest email",
    )


    # -- Job 4: Check for follow-ups every 24 hours --
    scheduler.add_job(
        func=lambda: _run(tasks.run_followup_cycle, "followup"),
        trigger="interval",
        hours=24,
        id="followup",
        name="Follow-up reminder drafting",
        start_date=_offset_start(hours=12),
    )
    return scheduler


def _offset_start(hours: int) -> datetime:
    """Return a start_date that is *hours* from now (UTC)."""
    from datetime import timedelta
    return datetime.now(timezone.utc) + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Manual run helper (triggered via env var MANUAL_TASK)
# ---------------------------------------------------------------------------

def _maybe_manual_run() -> None:
    """
    If MANUAL_TASK env var is set, run that task immediately and exit.
    Valid values: scrape | discover | draft | digest | followup | all
    """
    task_name = os.environ.get("MANUAL_TASK", "").strip().lower()
    if not task_name:
        return

    log.info("Manual run requested", task=task_name)
    dispatch = {
        "scrape":   tasks.run_scrape_cycle,
        "discover": tasks.run_discover_cycle,
        "draft":    tasks.run_draft_cycle,
        "digest":   tasks.run_digest_cycle,
        "followup": tasks.run_followup_cycle,
    }

    if task_name == "all":
        for name, fn in dispatch.items():
            _run(fn, name)
    elif task_name in dispatch:
        _run(dispatch[task_name], task_name)
    else:
        log.error("Unknown MANUAL_TASK", value=task_name, valid=list(dispatch) + ["all"])

    sys.exit(0)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    log.info(
        "Scheduler starting",
        crawl_interval_hours=CRAWL_INTERVAL_HOURS,
        discover_interval_hours=DISCOVER_INTERVAL_HOURS,
        gateway_url=os.environ.get("GATEWAY_URL", "http://gateway:8080"),
        role=os.environ.get("JOBSEEKER_ROLE", "Backend Engineer"),
    )

    _maybe_manual_run()   # exits if MANUAL_TASK is set

    scheduler = build_scheduler()
    scheduler.start()
    log.info("APScheduler started — waiting for signals.")

    # Block until SIGTERM / SIGINT
    while not _shutdown_event.is_set():
        time.sleep(1)

    log.info("Shutdown signal received — stopping scheduler (waiting for current job)…")
    scheduler.shutdown(wait=True)   # finish current job before exiting
    log.info("Scheduler stopped cleanly.")


if __name__ == "__main__":
    main()

