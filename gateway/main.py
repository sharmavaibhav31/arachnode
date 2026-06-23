"""
main.py — FastAPI API Gateway for the Job Discovery System.
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

import httpx  # type: ignore
from fastapi import FastAPI, HTTPException, Request  # type: ignore
from fastapi.responses import FileResponse, JSONResponse  # type: ignore

from pydantic import BaseModel  # type: ignore
from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore

import proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
SUMMARY_PATH   = Path(os.environ.get("SUMMARY_PATH", "/data/run_summary.json"))
NOTIFY_CONFIG_PATH = Path(os.environ.get("NOTIFY_CONFIG_PATH", "/data/notify_config.json"))

API_KEY = os.environ.get("JOBHUNTER_API_KEY", None)

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        public_paths = ["/", "/health", "/api/health"]
        if request.url.path in public_paths:
            return await call_next(request)
        
        if API_KEY is None:
            return await call_next(request)
        
        provided_key = (
            request.headers.get("X-API-Key") or 
            request.query_params.get("api_key")
        )
        
        if not provided_key or provided_key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized. Provide a valid API key."}
            )
        
        return await call_next(request)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if API_KEY is None:
        logger.warning("WARNING: JOBHUNTER_API_KEY is not set. Running in unauthenticated mode. Do not expose this on a public network.")
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

app.add_middleware(APIKeyMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "An internal error occurred",
            "path": str(request.url.path),
            "hint": "Check service logs for details"
        }
    )

@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(DASHBOARD_PATH, media_type="text/html")

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

@app.get("/api/summary", tags=["ops"])
async def run_summary():
    try:
        with open(SUMMARY_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"message": "No runs completed yet"}
    except json.JSONDecodeError:
        return {"message": "Summary is being written, try again shortly"}
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

@app.api_route("/api/scrape", methods=["GET", "POST"], tags=["proxy"])
async def proxy_scrape(request: Request):
    return await proxy.proxy_request(request, f"{proxy.SCRAPER_URL}/scrape")

@app.api_route("/api/contacts", methods=["GET", "POST"], tags=["proxy"])
async def proxy_contacts(request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/contacts")

@app.api_route("/api/contacts/{path:path}", methods=["GET", "DELETE"], tags=["proxy"])
async def proxy_contacts_path(path: str, request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/contacts/{path}")

@app.api_route("/api/discover", methods=["POST"], tags=["proxy"])
async def proxy_discover(request: Request):
    return await proxy.proxy_request(request, f"{proxy.CONTACT_URL}/discover")

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

class WorkflowRequest(BaseModel):
    job_id:   UUID
    template: Literal["cold_outreach", "recruiter_outreach", "referral_outreach", "followup"] = "cold_outreach"
    referred_by: Optional[str] = None
    roles:    list[str] = ["Engineering Manager", "Recruiter"]

async def poll_for_contacts(job_id: str, max_attempts: int = 10, interval: float = 2.0) -> list:
    """Poll the contacts endpoint until results appear or timeout."""
    for attempt in range(max_attempts):
        await asyncio.sleep(interval)
        try:
            # We can use the proxy client directly via httpx, or proxy_request but we need JSON
            # Here we just use the proxy.client
            client = proxy.get_client()
            response = await client.get(f"{proxy.CONTACT_URL}/contacts/{job_id}", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                contacts = data.get("data", data) # Handle pagination format if it changed
                if contacts:
                    return contacts
        except Exception:
            pass  # keep polling
    return []

@app.post("/api/workflow/apply", tags=["workflow"])
async def workflow_apply(body: WorkflowRequest):
    try:
        job = await proxy.get_job(body.job_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    await proxy.trigger_discovery(
        company=job["company"],
        job_id=body.job_id,
        roles=body.roles,
    )

    contacts = await poll_for_contacts(str(body.job_id))

    contact_id: Optional[UUID] = None
    if contacts:
        ordered = sorted(
            [c for c in contacts if c.get("verified") != "invalid"],
            key=lambda c: 0 if c.get("verified") == "verified" else 1,
        )
        if ordered:
            contact_id = UUID(ordered[0]["id"])

    email = None
    if contacts:
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

    if not contacts:
        # Create a placeholder draft email
        email = {
            "id": None,
            "status": "draft",
            "body": "Contact discovery is still running. Check back in 2 minutes.",
            "subject": "Discovery Pending"
        }

    return {
        "job":         job,
        "contacts":    contacts,
        "draft_email": email,
        "discovery_status": "complete" if contacts else "pending"
    }
