"""
main.py — FastAPI entrypoint for the Contact Discovery Service.

Endpoints
─────────
  POST /discover                     Run pipeline for a company
  GET  /contacts?company={company}   List contacts by company name
  GET  /contacts/{job_id}            List contacts by job UUID
  DELETE /contacts/{id}              Remove a contact record
  GET  /health                       Liveness probe
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from playwright.async_api import async_playwright

import storage
import discovery as disc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PLAYWRIGHT_AVAILABLE = True

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global PLAYWRIGHT_AVAILABLE
    await storage.create_pool()
    logger.info("Contact Discovery Service ready.")
    
    # Startup check for Playwright
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox"])
            await browser.close()
    except Exception as exc:
        logger.critical(f"Playwright unavailable: {exc}")
        PLAYWRIGHT_AVAILABLE = False

    yield
    await storage.close_pool()
    logger.info("Contact Discovery Service shut down.")


app = FastAPI(
    title="Contact Discovery Service",
    description=(
        "Discovers publicly available engineering and recruiting contacts "
        "for a given company and links them to job postings."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

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

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DiscoverRequest(BaseModel):
    company: str
    job_id: Optional[UUID] = None
    roles: list[str] = ["Engineering Manager", "Recruiter"]
    domain: Optional[str] = None   # override if you already know the domain


class ContactOut(BaseModel):
    id: UUID
    job_id: Optional[UUID]
    company: str
    domain: Optional[str]
    name: Optional[str]
    email: Optional[str]
    role: Optional[str]
    source: Optional[str]
    verified: str
    created_at: str

    @classmethod
    def from_record(cls, row) -> "ContactOut":
        d = dict(row)
        d["created_at"] = d["created_at"].isoformat()
        return cls(**d)


# ---------------------------------------------------------------------------
# Background task: run pipeline → persist
# ---------------------------------------------------------------------------

async def _discover_and_store(
    company: str,
    roles: list[str],
    job_id: Optional[UUID],
    domain: Optional[str],
) -> list[dict]:
    try:
        contacts = await disc.run_pipeline(company, roles, provided_domain=domain)
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        return []
        
    pool = await storage.get_pool()
    stored = []
    for c in contacts:
        try:
            row = await storage.upsert_contact(
                pool,
                job_id=job_id,
                company=c["company"],
                domain=c.get("domain"),
                name=c.get("name"),
                email=c.get("email"),
                role=c.get("role"),
                source=c.get("source"),
                verified=c.get("verified", "unverified"),
            )
            if row:
                stored.append(dict(row))
        except Exception as exc:
            logger.error("Failed to store contact %s: %s", c.get("email"), exc)
    return stored


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.post("/discover", tags=["discovery"])
async def discover(body: DiscoverRequest, background_tasks: BackgroundTasks):
    """
    Trigger contact discovery for a company.
    Runs asynchronously in the background; results are persisted to PostgreSQL.
    Poll GET /contacts?company=... to retrieve results.
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Contact discovery via LinkedIn is temporarily unavailable. GitHub-based discovery is still active."
        )

    background_tasks.add_task(
        _discover_and_store,
        body.company,
        body.roles,
        body.job_id,
        body.domain,
    )
    return {
        "triggered": True,
        "company": body.company,
        "roles": body.roles,
        "message": "Discovery running in background. Poll GET /contacts?company=... for results.",
    }


@app.get("/contacts", tags=["contacts"])
async def list_contacts_by_company(
    company: str = Query(..., description="Company name substring"),
    offset: int = 0,
    limit: int = 50
):
    pool = await storage.get_pool()
    try:
        import asyncio
        rows, total = await asyncio.gather(
            storage.get_contacts_by_company(pool, company, offset=offset, limit=limit),
            storage.get_contacts_count(pool, company)
        )
    except Exception as e:
        logger.error(f"DB Error: {e}")
        rows, total = [], 0
        
    return {
        "data": [ContactOut.from_record(r).dict() for r in rows],
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total
        }
    }


@app.get("/contacts/{job_id}", tags=["contacts"])
async def list_contacts_by_job(job_id: UUID, offset: int = 0, limit: int = 50):
    pool = await storage.get_pool()
    try:
        rows = await storage.get_contacts_by_job(pool, job_id, offset=offset, limit=limit)
    except Exception as e:
        logger.error(f"DB Error: {e}")
        rows = []
    
    return {
        "data": [ContactOut.from_record(r).dict() for r in rows],
        "pagination": {
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "has_more": False
        }
    }


@app.delete("/contacts/{contact_id}", status_code=204, tags=["contacts"])
async def remove_contact(contact_id: UUID):
    pool = await storage.get_pool()
    try:
        deleted = await storage.delete_contact(pool, contact_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Contact not found")
    except Exception as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(status_code=500, detail="Database error")
