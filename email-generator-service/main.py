"""
main.py — FastAPI entrypoint for the Cold Email Generator Service.

Endpoints
─────────
  POST /generate                     Generate and store an email
  GET  /emails?job_id={uuid}         List emails for a job
  GET  /emails/{id}                  Fetch a single email
  PATCH /emails/{id}/status          Update email status
  POST /emails/{id}/send             Send via Gmail SMTP
  GET  /health                       Liveness probe
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import generator
import mailer
import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.create_pool()
    logger.info("Email Generator Service ready.")
    yield
    await storage.close_pool()
    logger.info("Email Generator Service shut down.")


app = FastAPI(
    title="Cold Email Generator Service",
    description=(
        "Generates personalized cold emails from Jinja2 templates + optional "
        "Ollama LLM observations, stores them in PostgreSQL, and sends via Gmail."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    job_id:          Optional[UUID] = None
    contact_id:      Optional[UUID] = None
    template:        Literal["cold_outreach", "recruiter_outreach", "referral_outreach", "followup"]
    your_name:       str = ""
    your_stack:      List[str] = []
    github_url:      str = ""
    graduation_year: Optional[int] = None
    availability:    Optional[str] = None
    referred_by:     Optional[str] = None


class GenerateResponse(BaseModel):
    email_id: UUID
    subject:  str
    body:     str


class StatusUpdate(BaseModel):
    status: Literal["draft", "sent", "replied"]


class EmailOut(BaseModel):
    id:           UUID
    job_id:       Optional[UUID]
    contact_id:   Optional[UUID]
    template:     str
    subject:      str
    body:         str
    generated_at: str
    sent_at:      Optional[str]
    status:       str

    @classmethod
    def from_record(cls, row) -> "EmailOut":
        d = dict(row)
        d["generated_at"] = d["generated_at"].isoformat()
        d["sent_at"] = d["sent_at"].isoformat() if d.get("sent_at") else None
        return cls(**d)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.post("/generate", response_model=GenerateResponse, tags=["emails"])
async def generate(req: GenerateRequest):
    """
    Generate a personalized cold email and persist it to the database.

    - Fetches job and contact records from PostgreSQL (if IDs provided).
    - Calls Ollama for a product observation; falls back to YAML if unavailable.
    - Renders the requested Jinja2 template.
    - Returns the rendered subject, body, and stored email UUID.
    """
    pool = await storage.get_pool()

    # Resolve job and contact records
    job     = await storage.get_job_by_id(pool, req.job_id)     if req.job_id     else None
    contact = await storage.get_contact_by_id(pool, req.contact_id) if req.contact_id else None

    your_name   = req.your_name   or os.environ.get("YOUR_NAME", "Applicant")
    github_url  = req.github_url  or os.environ.get("YOUR_GITHUB_URL", "")

    try:
        subject, body = await generator.generate_email(
            template=req.template,
            job=job,
            contact=contact,
            your_name=your_name,
            your_stack=req.your_stack,
            github_url=github_url,
            graduation_year=req.graduation_year,
            availability=req.availability,
            referred_by=req.referred_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    row = await storage.insert_email(
        pool,
        job_id=req.job_id,
        contact_id=req.contact_id,
        template=req.template,
        subject=subject,
        body=body,
    )

    return GenerateResponse(email_id=row["id"], subject=subject, body=body)


@app.get("/emails", response_model=List[EmailOut], tags=["emails"])
async def list_emails(job_id: UUID):
    pool = await storage.get_pool()
    rows = await storage.get_emails_by_job(pool, job_id)
    return [EmailOut.from_record(r) for r in rows]


@app.get("/emails/{email_id}", response_model=EmailOut, tags=["emails"])
async def get_email(email_id: UUID):
    pool = await storage.get_pool()
    row  = await storage.get_email_by_id(pool, email_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailOut.from_record(row)


@app.patch("/emails/{email_id}/status", response_model=EmailOut, tags=["emails"])
async def patch_status(email_id: UUID, body: StatusUpdate):
    pool = await storage.get_pool()
    row  = await storage.update_status(pool, email_id, body.status)
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return EmailOut.from_record(row)


@app.post("/emails/{email_id}/send", response_model=EmailOut, tags=["emails"])
async def send_email_endpoint(email_id: UUID):
    """
    Send the email via Gmail SMTP using GMAIL_ADDRESS + GMAIL_APP_PASSWORD env vars.
    Fetches the contact's email address from the contacts table.
    Updates status to 'sent' and records sent_at on success.
    """
    pool     = await storage.get_pool()
    email_row = await storage.get_email_by_id(pool, email_id)
    if email_row is None:
        raise HTTPException(status_code=404, detail="Email not found")

    # Resolve recipient address from linked contact
    contact_id = email_row["contact_id"]
    to_address = None
    if contact_id:
        contact = await storage.get_contact_by_id(pool, contact_id)
        if contact:
            to_address = contact.get("email")

    if not to_address:
        raise HTTPException(
            status_code=422,
            detail="No recipient email address found. Link a contact with a verified email.",
        )

    try:
        await mailer.send_email(
            to_address=to_address,
            subject=email_row["subject"],
            body=email_row["body"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Gmail send failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"SMTP error: {exc}")

    row = await storage.mark_sent(pool, email_id)
    return EmailOut.from_record(row)
