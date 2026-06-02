"""
main.py — FastAPI API Gateway for the Job Discovery System.

Routes:
  /api/jobs/*         → aggregator:8000
  /api/scrape         → scraper:8001
  /api/contacts/*     → contact:8002
  /api/emails/*       → email-gen:8003

Composite endpoints (gateway-owned logic):
  POST /api/workflow/apply   Orchestrates job → discovery → email draft
  GET  /api/health           Fans out to all four services

Dashboard:
  GET  /                     Serves dashboard.html
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
SUMMARY_PATH   = Path(os.environ.get("SUMMARY_PATH", "/data/run_summary.json"))
NOTIFY_CONFIG_PATH = Path(os.environ.get("NOTIFY_CONFIG_PATH", "/data/notify_config.json"))


# ---------------------------------------------------------------------------
# Lifespan — shared httpx client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient()
    proxy.set_client(client)
    logger.info("API Gateway ready.")
    yield
    await client.aclose()
    logger.info("API Gateway shut down.")


app = FastAPI(
    title="Job Discovery Gateway",
    description="API Gateway and dashboard for the microservice-based job discovery system.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


# ---------------------------------------------------------------------------
# Health fan-out
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["ops"])
async def gateway_health():
    results = await asyncio.gather(
        proxy.health_check("aggregator", proxy.AGGREGATOR_URL),
        proxy.health_check("scraper",    proxy.SCRAPER_URL),
        proxy.health_check("contact",    proxy.CONTACT_URL),
        proxy.health_check("email-gen",  proxy.EMAIL_GEN_URL),
    )
    all_ok = all(r["status"] == "ok" for r in results)
    return JSONResponse(
        content={"gateway": "ok", "services": list(results)},
        status_code=200 if all_ok else 207,
    )


# ---------------------------------------------------------------------------
# Scheduler run summary
# ---------------------------------------------------------------------------

@app.get("/api/summary", tags=["ops"])
async def run_summary():
    """
    Returns the most recent scheduler run summary.
    Written by the scheduler service to /data/run_summary.json
    (mounted as a shared Docker volume).
    """
    if not SUMMARY_PATH.exists():
        return JSONResponse(
            content={"detail": "No run summary yet. Scheduler has not completed a cycle."},
            status_code=404,
        )
    try:
        data = json.loads(SUMMARY_PATH.read_text())
        return JSONResponse(content=data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read summary: {exc}")


# ---------------------------------------------------------------------------
# Notification config — stored in shared volume /data/notify_config.json
# ---------------------------------------------------------------------------

_NOTIFY_DEFAULTS = {
    "slack_webhook_url": os.environ.get("SLACK_WEBHOOK_URL", ""),
    "discord_webhook_url": os.environ.get("DISCORD_WEBHOOK_URL", ""),
    "notification_email": os.environ.get("NOTIFICATION_EMAIL", ""),
    "notify_events": ["jobs:new", "contacts:found", "emails:drafted", "emails:sent", "scrape:error", "cycle:complete"],
    "rate_limit_secs": int(os.environ.get("NOTIFY_RATE_LIMIT_SECS", "300")),
}


def _load_notify_config() -> dict:
    if NOTIFY_CONFIG_PATH.exists():
        try:
            return json.loads(NOTIFY_CONFIG_PATH.read_text())
        except Exception:
            pass
    return dict(_NOTIFY_DEFAULTS)


def _save_notify_config(data: dict) -> None:
    NOTIFY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFY_CONFIG_PATH.write_text(json.dumps(data, indent=2))


@app.get("/api/notifications/config", tags=["notifications"])
async def get_notify_config():
    return JSONResponse(content=_load_notify_config())


class NotifyConfigUpdate(BaseModel):
    slack_webhook_url: str = ""
    discord_webhook_url: str = ""
    notification_email: str = ""
    notify_events: list[str] = ["jobs:new", "contacts:found", "emails:drafted", "emails:sent", "scrape:error", "cycle:complete"]
    rate_limit_secs: int = 300


@app.put("/api/notifications/config", tags=["notifications"])
async def update_notify_config(body: NotifyConfigUpdate):
    _save_notify_config(body.model_dump())
    return JSONResponse(content={"status": "saved", **body.model_dump()})


@app.post("/api/notifications/test", tags=["notifications"])
async def send_test_notification(channel: str = "slack"):
    """
    Send a test notification to verify channel configuration.
    The gateway sends this directly to avoid requiring an HTTP endpoint on the scheduler.
    channel: slack | discord | email
    """
    config = _load_notify_config()
    payload = {
        "title": "Test Notification from Arachnode",
        "message": "This is a test notification. Your notification channel is configured correctly!",
        "fields": {"service": "Arachnode Gateway", "version": "1.0.0", "channel": channel},
        "severity": "info",
    }

    try:
        if channel == "slack":
            url = config.get("slack_webhook_url", "")
            if not url:
                raise HTTPException(status_code=400, detail="Slack webhook URL not configured")
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": payload["title"]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
                {"type": "section", "fields": [{"type": "mrkdwn", "text": f"*{k}:* {v}"} for k, v in payload["fields"].items()]},
            ]
            body = {"attachments": [{"color": "#4f9eff", "blocks": blocks}]}

        elif channel == "discord":
            url = config.get("discord_webhook_url", "")
            if not url:
                raise HTTPException(status_code=400, detail="Discord webhook URL not configured")
            embed = {
                "title": payload["title"],
                "description": payload["message"],
                "color": 0x4F9EFF,
                "fields": [{"name": k, "value": str(v), "inline": True} for k, v in payload["fields"].items()],
            }
            body = {"embeds": [embed]}

        elif channel == "email":
            to_addr = config.get("notification_email", "")
            gmail = os.environ.get("GMAIL_ADDRESS", "")
            if not to_addr:
                raise HTTPException(status_code=400, detail="Notification email not configured")
            if not gmail:
                raise HTTPException(status_code=400, detail="GMAIL_ADDRESS not set — email notifications require SMTP config")
            return JSONResponse(content={
                "status": "config_valid",
                "channel": channel,
                "detail": "Email config saved. Test email will be sent on next scheduler cycle.",
            })

        else:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {channel}")

        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(url, json=body)
            resp.raise_for_status()
        return JSONResponse(content={"status": "ok", "channel": channel})

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Test notification failed: {exc}")


# ---------------------------------------------------------------------------
# Proxy routes — /api/jobs/*
# ---------------------------------------------------------------------------

@app.api_route("/api/jobs", methods=["GET", "POST"], tags=["proxy"])
async def proxy_jobs(request: Request):
    return await proxy.proxy_request(request, f"{proxy.AGGREGATOR_URL}/jobs")


@app.api_route("/api/jobs/export", methods=["GET"], tags=["proxy"])
async def proxy_jobs_export(request: Request):
    return await proxy.proxy_request(request, f"{proxy.AGGREGATOR_URL}/jobs/export")


@app.api_route("/api/jobs/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"], tags=["proxy"])
async def proxy_jobs_path(path: str, request: Request):
    return await proxy.proxy_request(request, f"{proxy.AGGREGATOR_URL}/jobs/{path}")


@app.get("/api/stats", tags=["proxy"])
async def proxy_stats(request: Request):
    return await proxy.proxy_request(request, f"{proxy.AGGREGATOR_URL}/stats")


# ---------------------------------------------------------------------------
# Proxy routes — /api/scrape
# ---------------------------------------------------------------------------

@app.api_route("/api/scrape", methods=["GET", "POST"], tags=["proxy"])
async def proxy_scrape(request: Request):
    return await proxy.proxy_request(request, f"{proxy.SCRAPER_URL}/scrape")


# ---------------------------------------------------------------------------
# Proxy routes — /api/contacts/*
# ---------------------------------------------------------------------------

@app.api_route("/api/contacts", methods=["GET", "POST"], tags=["proxy"])
async def proxy_contacts(request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/contacts")


@app.api_route("/api/contacts/{path:path}", methods=["GET", "DELETE"], tags=["proxy"])
async def proxy_contacts_path(path: str, request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/contacts/{path}")


@app.api_route("/api/discover", methods=["POST"], tags=["proxy"])
async def proxy_discover(request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/discover")


# ---------------------------------------------------------------------------
# Proxy routes — /api/emails/*
# ---------------------------------------------------------------------------

@app.api_route("/api/emails", methods=["GET"], tags=["proxy"])
async def proxy_emails(request: Request):
    return await proxy.proxy_request(request, f"{proxy.EMAIL_GEN_URL}/emails")


@app.api_route("/api/emails/{path:path}", methods=["GET", "PATCH", "POST"], tags=["proxy"])
async def proxy_emails_path(path: str, request: Request):
    return await proxy.proxy_request(request, f"{proxy.EMAIL_GEN_URL}/emails/{path}")


@app.api_route("/api/generate", methods=["POST"], tags=["proxy"])
async def proxy_generate(request: Request):
    return await proxy.proxy_request(request, f"{proxy.EMAIL_GEN_URL}/generate")


@app.api_route("/api/digest", methods=["POST"], tags=["proxy"])
async def proxy_digest(request: Request):
    return await proxy.proxy_request(request, f"{proxy.EMAIL_GEN_URL}/digest")


# ---------------------------------------------------------------------------
# Composite endpoint — POST /api/workflow/apply
# ---------------------------------------------------------------------------

class WorkflowRequest(BaseModel):
    job_id:   UUID
    template: Literal["cold_outreach", "recruiter_outreach", "referral_outreach", "followup"] = "cold_outreach"
    referred_by: Optional[str] = None
    roles:    list[str] = ["Engineering Manager", "Recruiter"]


@app.post("/api/workflow/apply", tags=["workflow"])
async def workflow_apply(body: WorkflowRequest):
    """
    Composite workflow:
      1. Fetch job details from aggregator.
      2. Trigger contact discovery (fire-and-wait pattern).
      3. Wait briefly then poll for contacts.
      4. Generate a draft email for the first verified/unverified contact.
      5. Return job + contacts + draft email in a single response.
    """
    # Step 1 — Job details
    job = await proxy.get_job(body.job_id)

    # Step 2 — Trigger discovery (runs in background on the contact service)
    await proxy.trigger_discovery(
        company=job["company"],
        job_id=body.job_id,
        roles=body.roles,
    )

    # Step 3 — Wait for the background pipeline to populate contacts
    # (contact discovery is fire-and-background; the aggregator typically
    #  completes the DB-only part in <2 s when names are already known)
    await asyncio.sleep(3)
    contacts = await proxy.get_contacts_for_company(job["company"])

    # Step 4 — Pick the best contact for email generation
    contact_id: Optional[UUID] = None
    if contacts:
        # Prefer verified > unverified; ignore 'invalid'
        ordered = sorted(
            [c for c in contacts if c.get("verified") != "invalid"],
            key=lambda c: 0 if c.get("verified") == "verified" else 1,
        )
        if ordered:
            contact_id = UUID(ordered[0]["id"])

    # Step 5 — Generate email draft
    try:
        email = await proxy.generate_email(
            job_id=body.job_id,
            contact_id=contact_id,
            template=body.template,
            referred_by=body.referred_by,
        )
    except Exception as exc:
        logger.warning("Email generation failed: %s", exc)
        email = None

    return {
        "job":         job,
        "contacts":    contacts,
        "draft_email": email,
    }

