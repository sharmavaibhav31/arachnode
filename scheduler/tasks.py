"""
tasks.py — Scheduled task implementations for the Scheduler Service.

Each public function corresponds to one APScheduler job:

  run_scrape_cycle()      → POST /scrape + scrapy subprocess  (every 8 h)
  run_discover_cycle()    → POST /api/discover for new jobs    (every 24 h)
  run_draft_cycle()       → POST /api/generate for new jobs    (every 24 h)

All functions are synchronous (APScheduler runs them in a thread-pool executor).
They write their results into a shared state dict that main.py flushes to
/data/run_summary.json after each execution.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import timedelta
from typing import Any

import httpx

from logger import get_logger

log = get_logger("scheduler.tasks")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _gw() -> str:
    return os.environ.get("GATEWAY_URL", "http://gateway:8080").rstrip("/")

def _role() -> str:
    return os.environ.get("JOBSEEKER_ROLE", "Backend Engineer")

def _stack() -> list[str]:
    raw = os.environ.get("JOBSEEKER_STACK", "Python,FastAPI,PostgreSQL,Redis,Go")
    return [s.strip() for s in raw.split(",") if s.strip()]

_HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_SCRAPER_WAIT_SECS  = int(os.environ.get("SCRAPER_WAIT_SECS", 60))
_DISCOVER_DELAY_SECS = int(os.environ.get("DISCOVER_DELAY_SECS", 30))

# Shared mutable summary updated by tasks and flushed by main.py
_summary: dict[str, Any] = {
    "jobs_discovered": 0,
    "contacts_found":  0,
    "emails_drafted":  0,
    "errors":          [],
}


def reset_summary() -> None:
    _summary.update(jobs_discovered=0, contacts_found=0, emails_drafted=0, errors=[])


def get_summary() -> dict[str, Any]:
    return dict(_summary)


def _record_error(context: str, detail: str) -> None:
    _summary["errors"].append({"context": context, "detail": detail})
    log.error("Task error", context=context, detail=detail)


# ---------------------------------------------------------------------------
# Helper: count jobs currently in the stream
# ---------------------------------------------------------------------------

def _job_count() -> int:
    try:
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{_gw()}/api/stats")
            r.raise_for_status()
            by_status = r.json().get("by_status", {})
            return sum(by_status.values())
    except Exception as exc:
        log.warning("Could not fetch job count", error=str(exc))
        return 0


# ---------------------------------------------------------------------------
# Task 1 — Scrape cycle  (every CRAWL_INTERVAL_HOURS)
# ---------------------------------------------------------------------------

def run_scrape_cycle() -> None:
    """
    1. POST /api/scrape   — trigger platform scrapers (Naukri/LI/Internshala)
    2. Run Scrapy spiders — remotive + yc_jobs via subprocess
    3. Wait SCRAPER_WAIT_SECS for pipelines to flush
    4. Count delta jobs and record in summary
    """
    log.info("Scrape cycle starting", role=_role(), stack=_stack())
    jobs_before = _job_count()

    # 1. Platform scrapers via gateway
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.post(
                f"{_gw()}/api/scrape",
                json={"role": _role(), "stack": _stack()},
            )
            r.raise_for_status()
        log.info("Platform scraper triggered", response=r.json())
    except Exception as exc:
        _record_error("platform_scrape", str(exc))

    # 2. Scrapy spiders (subprocess — crawler-service must be on PATH or CWD)
    scrapy_dir = os.environ.get("SCRAPY_PROJECT_DIR", "/crawler")
    for spider in ("remotive", "yc_jobs"):
        log.info("Running Scrapy spider", spider=spider, cwd=scrapy_dir)
        try:
            proc = subprocess.run(
                ["scrapy", "crawl", spider],
                capture_output=True, text=True,
                timeout=300,
                cwd=scrapy_dir,
            )
            if proc.returncode == 0:
                log.info("Spider finished", spider=spider, stdout_lines=proc.stdout.count("\n"))
            else:
                _record_error(f"scrapy_{spider}", proc.stderr[-500:])
        except FileNotFoundError:
            log.warning("scrapy not found in PATH — skipping subprocess crawl", spider=spider)
        except subprocess.TimeoutExpired:
            _record_error(f"scrapy_{spider}", "timeout after 300s")
        except Exception as exc:
            _record_error(f"scrapy_{spider}", str(exc))

    # 3. Wait for pipelines
    log.info("Waiting for scrape pipelines to flush", seconds=_SCRAPER_WAIT_SECS)
    time.sleep(_SCRAPER_WAIT_SECS)

    # 4. Delta
    jobs_after = _job_count()
    delta = max(jobs_after - jobs_before, 0)
    _summary["jobs_discovered"] += delta
    log.info("Scrape cycle complete", jobs_before=jobs_before, jobs_after=jobs_after, delta=delta)


# ---------------------------------------------------------------------------
# Task 2 — Discover cycle  (every DISCOVER_INTERVAL_HOURS)
# ---------------------------------------------------------------------------

def run_discover_cycle() -> None:
    """
    For each new job (up to 20), POST /api/discover to find contacts.
    Respects a DISCOVER_DELAY_SECS pause between calls.
    """
    log.info("Discover cycle starting")

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(f"{_gw()}/api/jobs", params={"status": "new", "limit": 20})
            r.raise_for_status()
            jobs = r.json()
    except Exception as exc:
        _record_error("discover_fetch_jobs", str(exc))
        return

    log.info("Jobs to process for contact discovery", count=len(jobs))
    found = 0

    for job in jobs:
        jid = job.get("id")
        company = job.get("company", "unknown")
        log.info("Discovering contacts", job_id=jid, company=company)
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
                r = c.post(
                    f"{_gw()}/api/discover",
                    json={
                        "company": company,
                        "job_id":  jid,
                        "roles":   ["Engineering Manager", "Recruiter"],
                    },
                )
                r.raise_for_status()
            found += 1
        except Exception as exc:
            _record_error(f"discover_{jid}", str(exc))

        time.sleep(_DISCOVER_DELAY_SECS)

    _summary["contacts_found"] += found
    log.info("Discover cycle complete", triggered=found)


# ---------------------------------------------------------------------------
# Task 3 — Draft cycle  (every DISCOVER_INTERVAL_HOURS + 4 h offset)
# ---------------------------------------------------------------------------

def run_draft_cycle() -> None:
    """
    For each new job that now has contacts, pre-generate a cold_outreach draft.
    Polls GET /api/contacts?company={company} to check for contact availability.
    """
    log.info("Draft cycle starting")

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(f"{_gw()}/api/jobs", params={"status": "new", "limit": 20})
            r.raise_for_status()
            jobs = r.json()
    except Exception as exc:
        _record_error("draft_fetch_jobs", str(exc))
        return

    drafted = 0
    for job in jobs:
        jid     = job.get("id")
        company = job.get("company", "")

        # Only draft if we have at least one contact for this company
        try:
            with httpx.Client(timeout=20) as c:
                cr = c.get(f"{_gw()}/api/contacts", params={"company": company})
                contacts = cr.json() if cr.status_code == 200 else []
        except Exception:
            contacts = []

        if not contacts:
            log.debug("No contacts yet, skipping draft", job_id=jid, company=company)
            continue

        # Pick best contact (verified > unverified)
        ordered = sorted(
            [x for x in contacts if x.get("verified") != "invalid"],
            key=lambda x: 0 if x.get("verified") == "verified" else 1,
        )
        contact_id = ordered[0]["id"] if ordered else None

        log.info("Generating draft email", job_id=jid, company=company, contact_id=contact_id)
        try:
            payload: dict[str, Any] = {"job_id": jid, "template": "cold_outreach"}
            if contact_id:
                payload["contact_id"] = contact_id

            with httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0)) as c:
                r = c.post(f"{_gw()}/api/generate", json=payload)
                r.raise_for_status()
            drafted += 1
            log.info("Draft created", job_id=jid, email_id=r.json().get("email_id"))
        except Exception as exc:
            _record_error(f"draft_{jid}", str(exc))

        time.sleep(2)   # light throttle — Ollama can be slow

    _summary["emails_drafted"] += drafted
    log.info("Draft cycle complete", drafted=drafted)


# ---------------------------------------------------------------------------
# Task 4 — Weekly digest cycle  (every Sunday at 09:00 UTC)
# ---------------------------------------------------------------------------

def run_digest_cycle() -> None:
    """
    Fetch all new jobs from the past 7 days and POST them to the email-generator
    service's /digest endpoint, which filters for freshness, groups by source,
    renders the digest template, and sends the email via Gmail SMTP.
    """

    log.info("Digest cycle starting")

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%d %b')}–{week_end.strftime('%d %b %Y')}"

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(
                f"{_gw()}/api/jobs",
                params={
                    "status": "new",
                    "limit": 100,
                    "sort": "latest",
                },
            )
            r.raise_for_status()
            jobs = r.json()

    except Exception as exc:
        _record_error("digest_fetch_jobs", str(exc))
        log.error("Digest cycle aborted — could not fetch jobs", error=str(exc))
        return

    if not jobs:
        log.info("Digest cycle: no new jobs found — skipping send")
        return

    log.info("Digest cycle: fetched %d new jobs", len(jobs))

    try:
        with httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0)) as c:
            r = c.post(
                f"{_gw()}/api/digest",
                json={
                    "jobs": jobs,
                    "week_label": week_label,
                },
            )
            r.raise_for_status()
            result = r.json()

    except Exception as exc:
        _record_error("digest_send", str(exc))
        log.error("Digest cycle: email send failed", error=str(exc))
        return

    log.info(
        "Digest cycle complete",
        sent=result.get("sent"),
        recipient=result.get("recipient"),
        job_count=result.get("job_count"),
        subject=result.get("subject"),
    )

    _summary["digest_sent"] = result.get("job_count", 0)
