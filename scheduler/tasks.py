"""
tasks.py — Scheduled task implementations for the Scheduler Service.
"""

from __future__ import annotations

import json
import os
import time
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from logger import get_logger

log = get_logger("scheduler.tasks")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _gw() -> str:
    return os.environ.get("GATEWAY_URL", "http://gateway:8080").rstrip("/")

def _crawler_url() -> str:
    return os.environ.get("CRAWLER_URL", "http://crawler:8004").rstrip("/")

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


def write_summary(summary: dict, path: str = "/data/run_summary.json"):
    dir_name = os.path.dirname(path)
    if not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode='w', 
        dir=dir_name, 
        delete=False, 
        suffix='.tmp'
    ) as tmp:
        json.dump(summary, tmp, default=str, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)

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
    log.info("Scrape cycle starting", role=_role(), stack=_stack())
    jobs_before = _job_count()

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

    for spider in ("remotive", "yc_jobs", "wellfound", "cutshort", "glassdoor"):
        log.info("Triggering Scrapy spider via HTTP", spider=spider)
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as c:
                r = c.post(
                    f"{_crawler_url()}/crawl",
                    json={"spider": spider}
                )
                r.raise_for_status()
                log.info("Spider triggered", spider=spider, stdout_lines=r.json())
        except Exception as exc:
            _record_error(f"scrapy_{spider}", str(exc))

    log.info("Waiting for scrape pipelines to flush", seconds=_SCRAPER_WAIT_SECS)
    time.sleep(_SCRAPER_WAIT_SECS)

    jobs_after = _job_count()
    delta = max(jobs_after - jobs_before, 0)
    _summary["jobs_discovered"] += delta
    log.info("Scrape cycle complete", jobs_before=jobs_before, jobs_after=jobs_after, delta=delta)

# ---------------------------------------------------------------------------
# Task 2 — Discover cycle  (every DISCOVER_INTERVAL_HOURS)
# ---------------------------------------------------------------------------

def run_discover_cycle() -> None:
    log.info("Discover cycle starting")
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(f"{_gw()}/api/jobs", params={"status": "new", "limit": 20})
            r.raise_for_status()
            data = r.json()
            jobs = data.get("data", data) if isinstance(data, dict) else data
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
    log.info("Draft cycle starting")
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.get(f"{_gw()}/api/jobs", params={"status": "new", "limit": 20})
            r.raise_for_status()
            data = r.json()
            jobs = data.get("data", data) if isinstance(data, dict) else data
    except Exception as exc:
        _record_error("draft_fetch_jobs", str(exc))
        return

    drafted = 0
    for job in jobs:
        jid     = job.get("id")
        company = job.get("company", "")

        try:
            with httpx.Client(timeout=20) as c:
                cr = c.get(f"{_gw()}/api/contacts", params={"company": company})
                # Check for dict wrapper with 'data' since we added pagination
                data = cr.json() if cr.status_code == 200 else []
                contacts = data.get("data", data) if isinstance(data, dict) else data
        except Exception:
            contacts = []

        if not contacts:
            log.debug("No contacts yet, skipping draft", job_id=jid, company=company)
            continue

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

        time.sleep(2)

    _summary["emails_drafted"] += drafted
    log.info("Draft cycle complete", drafted=drafted)

# ---------------------------------------------------------------------------
# Task 4 — Weekly digest cycle  (every Sunday at 09:00 UTC)
# ---------------------------------------------------------------------------

def run_digest_cycle() -> None:
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
            data = r.json()
            jobs = data.get("data", data) if isinstance(data, dict) else data
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

# --------------------------------------------------------------------------
# Follow-up scheduling cycle
# --------------------------------------------------------------------------

FOLLOWUP_DAYS = int(os.getenv("FOLLOWUP_DAYS", 7))

def run_followup_cycle() -> None:
    log.info("Follow-up cycle started", followup_days=FOLLOWUP_DAYS)
    reminded = 0

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
            r = c.get(
                f"{_gw()}/api/emails",
                params={"status": "sent"},
            )
            r.raise_for_status()
            emails = r.json()
    except Exception as exc:
        _record_error("followup_fetch", str(exc))
        log.warning("Follow-up cycle: could not fetch sent emails", error=str(exc))
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=FOLLOWUP_DAYS)

    for email in emails:
        sent_at_raw = email.get("sent_at")
        if not sent_at_raw:
            continue

        try:
            sent_at = datetime.fromisoformat(sent_at_raw.replace("Z", "+00:00"))
        except ValueError:
            continue

        if sent_at > cutoff:
            continue

        if email.get("followup_status") == "pending_followup":
            continue

        eid = email.get("id")
        jid = email.get("job_id")

        payload = {
            "email_id": eid,
            "job_id": jid,
            "template": "followup",
            "action": "pending_followup",
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0)) as c:
                r = c.post(f"{_gw()}/api/generate", json=payload)
                r.raise_for_status()
                reminded += 1
        except Exception as exc:
            _record_error(f"followup_{eid}", str(exc))

    _summary["followups_drafted"] = _summary.get("followups_drafted", 0) + reminded
    log.info("Follow-up cycle complete", reminded=reminded)
