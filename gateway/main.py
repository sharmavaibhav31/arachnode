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
