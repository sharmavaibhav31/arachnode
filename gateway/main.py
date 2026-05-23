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


# ---------------------------------------------------------------------------
# Composite endpoint — POST /api/workflow/apply
# ---------------------------------------------------------------------------

class WorkflowRequest(BaseModel):
    job_id:   UUID
    template: Literal["cold_outreach", "recruiter_outreach", "followup"] = "cold_outreach"
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
        )
    except Exception as exc:
        logger.warning("Email generation failed: %s", exc)
        email = None

    return {
        "job":      job,
        "contacts": contacts,
        "draft_email": email,
    }


