"""
main.py — FastAPI application for Referral Outreach Service.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from datetime import date as date_lib
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

import storage
from classifier import classify_position

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
)

TEMPLATE_MAP = {
    "hr": "hr_outreach.j2",
    "technical": "technical_outreach.j2",
    "leadership": "leadership_outreach.j2",
    "other": "other_outreach.j2",
    "unknown": "other_outreach.j2",
}


def render_draft(
    contact_type: str,
    first_name: Optional[str],
    company: Optional[str],
    position: Optional[str],
) -> tuple[str, str]:
    stack = os.environ.get("REFERRAL_STACK", "Python,FastAPI,PostgreSQL")
    opportunity_type = os.environ.get(
        "REFERRAL_OPPORTUNITY_TYPE", "both full-time and internship"
    )

    template_name = TEMPLATE_MAP.get(contact_type, "other_outreach.j2")
    template = jinja_env.get_template(template_name)

    clean_first_name = (first_name or "").strip()
    clean_company = (company or "").strip() or "your company"
    clean_position = (position or "").strip()[:40]

    draft = template.render(
        first_name=clean_first_name,
        company=clean_company,
        their_role=clean_position,
        stack=stack,
        opportunity_type=opportunity_type,
    )
    return draft, template_name


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.create_pool()
    logger.info("Referral Service ready.")
    yield
    await storage.close_pool()
    logger.info("Referral Service shut down.")


app = FastAPI(
    title="Referral Outreach Service",
    description="Manages LinkedIn connection imports, outreach draft generation, and daily sending queue.",
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
            "hint": "Check service logs for details",
        },
    )


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.post("/import", tags=["import"])
async def import_connections(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv file")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to decode CSV: {e}")

    lines = text.splitlines()
    if len(lines) < 4:
        raise HTTPException(
            status_code=400,
            detail="CSV file must have at least 4 lines (3 notes/header lines + data)",
        )

    # Skip first 3 header/notes lines
    csv_data_lines = lines[3:]
    reader = csv.DictReader(csv_data_lines)

    contacts_to_insert = []
    for row in reader:
        url = (row.get("URL") or "").strip()
        if not url:
            continue

        first_name = (row.get("First Name") or "").strip()
        last_name = (row.get("Last Name") or "").strip()
        email = (row.get("Email Address") or "").strip()
        company = (row.get("Company") or "").strip()
        position = (row.get("Position") or "").strip()
        connected_on = (row.get("Connected On") or "").strip()

        ctype = classify_position(position)
        draft, template_used = render_draft(ctype, first_name, company, position)

        contacts_to_insert.append(
            {
                "first_name": first_name or "Connection",
                "last_name": last_name,
                "linkedin_url": url,
                "email": email,
                "company": company,
                "position": position,
                "connected_on": connected_on,
                "contact_type": ctype,
                "status": "pending",
                "message_draft": draft,
                "template_used": template_used,
            }
        )

    if not contacts_to_insert:
        return {
            "imported": 0,
            "skipped_duplicates": 0,
            "by_type": {"hr": 0, "technical": 0, "leadership": 0, "other": 0, "unknown": 0},
        }

    res = await storage.import_contacts(contacts_to_insert)
    return res


@app.get("/contacts", tags=["contacts"])
async def list_contacts(
    type: str = Query("all", description="Contact type filter: hr|technical|leadership|other|unknown|all"),
    status: str = Query("all", description="Status filter: pending|queued|sent|replied|skipped|all"),
    limit: int = Query(50, ge=1, le=500, description="Max items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    company: Optional[str] = Query(None, description="Company filter substring"),
):
    valid_types = {"hr", "technical", "leadership", "other", "unknown", "all"}
    valid_statuses = {"pending", "queued", "sent", "replied", "skipped", "all"}

    if type.lower() not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type filter: {type}")
    if status.lower() not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status filter: {status}")

    contacts, total = await storage.get_contacts(
        contact_type=type,
        status=status,
        limit=limit,
        offset=offset,
        company=company,
    )

    return {
        "data": contacts,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        },
    }


@app.get("/contacts/{contact_id}", tags=["contacts"])
async def get_contact(contact_id: UUID):
    contact = await storage.get_contact_by_id(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


class ContactUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    message_draft: Optional[str] = None


@app.patch("/contacts/{contact_id}", tags=["contacts"])
async def update_contact(contact_id: UUID, body: ContactUpdateRequest):
    if body.status:
        valid_statuses = {"pending", "queued", "sent", "replied", "skipped"}
        if body.status.lower() not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    updated = await storage.update_contact(
        contact_id=contact_id,
        status=body.status,
        notes=body.notes,
        message_draft=body.message_draft,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return updated


@app.post("/contacts/{contact_id}/regenerate", tags=["contacts"])
async def regenerate_contact_draft(contact_id: UUID):
    contact = await storage.get_contact_by_id(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    draft, template_used = render_draft(
        contact_type=contact["contact_type"],
        first_name=contact["first_name"],
        company=contact["company"],
        position=contact["position"],
    )

    updated = await storage.update_contact_draft(contact_id, draft, template_used)
    return updated


@app.get("/queue/today", tags=["queue"])
async def get_queue_today():
    today_str = date_lib.today().isoformat()
    return await storage.get_queue_for_date(today_str)


class QueueGenerateRequest(BaseModel):
    date: Optional[str] = None
    count: int = Field(12, ge=1, le=15)
    prefer_types: Optional[List[str]] = None


@app.post("/queue/generate", tags=["queue"])
async def generate_queue(body: QueueGenerateRequest):
    target_date = body.date if body.date else date_lib.today().isoformat()
    return await storage.generate_queue(
        target_date=target_date,
        count=body.count,
        prefer_types=body.prefer_types,
    )


class MarkSentRequest(BaseModel):
    contact_ids: List[UUID]


@app.post("/queue/mark-sent", tags=["queue"])
async def mark_sent(body: MarkSentRequest):
    if not body.contact_ids:
        return {"updated": 0}
    count = await storage.mark_contacts_sent(body.contact_ids)
    return {"updated": count}


@app.get("/stats", tags=["stats"])
async def get_stats():
    return await storage.get_stats()
