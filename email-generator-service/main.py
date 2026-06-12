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
import generator_digest
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


class DigestRequest(BaseModel):
    """
    Payload sent by the scheduler to trigger a weekly digest email.

    Fields
    ------
    jobs : list[dict]
        Raw job records from GET /api/jobs — the email-generator does its
        own staleness filtering here, keeping the scheduler orchestration-light.

    recipient_email : str
        Who receives the digest. Defaults to GMAIL_ADDRESS env var if omitted.
        This lets the system self-send as a personal digest without extra config.

    your_name : str
        The user's display name for the greeting line.
        Defaults to the YOUR_NAME env var.

    week_label : str
        Human-readable date range, e.g. "12–18 May 2026".
        The scheduler computes and passes this so the template doesn't need
        datetime logic.
    """
    jobs: List[dict]
    recipient_email: Optional[str] = None
    your_name: str = ""
    week_label: str = ""


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


@app.post("/digest", tags=["emails"])
async def send_digest(req: DigestRequest):
    """
    Generate and immediately send a weekly job digest email.

    Steps performed here:
      1. Resolve recipient address (request body → GMAIL_ADDRESS env var).
      2. Resolve sender name (request body → YOUR_NAME env var).
      3. Compute a week_label if the caller didn't provide one.
      4. Call generator_digest.generate_digest() to filter, group, and render.
      5. Send the rendered email via the existing mailer.send_email().
      6. Return a summary of what was sent.

    This endpoint intentionally does NOT store the digest in the emails table.
    The digest is a notification, not an outreach draft that needs tracking.
    If the owner later wants storage, a separate PR can add it.
    """

    recipient = (
        req.recipient_email
        or os.environ.get("DIGEST_RECIPIENT_EMAIL", "").strip()
        or os.environ.get("GMAIL_ADDRESS", "").strip()
    )

    if not recipient:
        raise HTTPException(
            status_code=422,
            detail=(
                "No recipient address. Set DIGEST_RECIPIENT_EMAIL or GMAIL_ADDRESS "
                "in environment, or pass recipient_email in the request body."
            ),
        )

    your_name = req.your_name or os.environ.get("YOUR_NAME", "Applicant").strip()

    if req.week_label:
        week_label = req.week_label
    else:
        from datetime import timedelta, timezone as _tz
        today = datetime.now(_tz.utc)
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        week_label = f"{week_start.strftime('%d %b')}–{week_end.strftime('%d %b %Y')}"

    try:
        subject, body = generator_digest.generate_digest(
            jobs=req.jobs,
            your_name=your_name,
            week_label=week_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        await mailer.send_email(
            to_address=recipient,
            subject=subject,
            body=body,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Digest email send failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"SMTP error: {exc}")

    return {
        "sent": True,
        "recipient": recipient,
        "subject": subject,
        "job_count": len(req.jobs),
    }
