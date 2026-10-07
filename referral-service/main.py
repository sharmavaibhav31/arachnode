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

import openpyxl
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from jinja2 import Environment, FileSystemLoader, Template, TemplateSyntaxError
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
    "unknown": "unknown_outreach.j2",
}


def get_candidate_profile() -> Dict[str, str]:
    return {
        "name": os.getenv("REFERRAL_YOUR_NAME", "Vaibhav Sharma"),
        "role_target": os.getenv("REFERRAL_TARGET_ROLE", "Software Engineer"),
        "opportunity_type": os.getenv(
            "REFERRAL_OPPORTUNITY_TYPE", "both full-time and internship"
        ),
        "stack": os.getenv(
            "REFERRAL_STACK",
            "Python, FastAPI, Java, Spring Boot, Node.js, PostgreSQL, Redis, Docker",
        ),
        "graduation_year": os.getenv("REFERRAL_GRADUATION_YEAR", "2027"),
        "college": os.getenv("REFERRAL_COLLEGE", "MITE Mangalore"),
        "cgpa": os.getenv("REFERRAL_CGPA", "9.37"),
        "github": os.getenv("REFERRAL_GITHUB", "github.com/sharmavaibhav31"),
        "portfolio": os.getenv("REFERRAL_PORTFOLIO", "vaibhavsharmaa.me"),
        "highlight_1": os.getenv(
            "REFERRAL_HIGHLIGHT_1",
            "built an AI workflow feature at LazyStudents.in and led a 5-member intern team",
        ),
        "highlight_2": os.getenv(
            "REFERRAL_HIGHLIGHT_2",
            "run Arachnode, an open-source microservices project with 75+ PRs reviewed on GitHub",
        ),
    }


async def render_draft(
    contact_type: str,
    first_name: Optional[str],
    company: Optional[str],
    position: Optional[str],
    override_template_body: Optional[str] = None,
) -> tuple[str, str]:
    profile = get_candidate_profile()

    clean_first_name = (first_name or "").strip() or "there"
    clean_company = (company or "").strip() or "your company"
    clean_position = (position or "").strip()[:40] or "team member"

    context = {
        "first_name": clean_first_name,
        "company": clean_company,
        "their_role": clean_position,
        "contact_type": contact_type,
        "profile": profile,
    }

    if override_template_body:
        try:
            tmpl = jinja_env.from_string(override_template_body)
            return tmpl.render(**context), "custom_override"
        except Exception as e:
            logger.error(f"Failed to render override template: {e}")

    # Check active template from database
    db_tmpl = await storage.get_active_template_for_type(contact_type)
    if db_tmpl and db_tmpl.get("body"):
        try:
            tmpl = jinja_env.from_string(db_tmpl["body"])
            return tmpl.render(**context), db_tmpl.get("name", "custom_db_template")
        except Exception as e:
            logger.error(f"Failed to render DB template '{db_tmpl.get('name')}': {e}")

    # Fallback to .j2 template file on disk
    template_filename = TEMPLATE_MAP.get(contact_type, "other_outreach.j2")
    try:
        template = jinja_env.get_template(template_filename)
        return template.render(**context), template_filename
    except Exception as e:
        logger.error(f"Failed to render fallback disk template {template_filename}: {e}")
        return f"Hi {clean_first_name},\n\nReaching out regarding opportunities at {clean_company}.", "default_fallback"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage.create_pool()
    logger.info("Referral Service ready.")
    yield
    await storage.close_pool()
    logger.info("Referral Service shut down.")


app = FastAPI(
    title="Referral Outreach Service",
    description="Manages LinkedIn connection imports, outreach draft generation, custom templates, and daily sending queue.",
    version="1.1.0",
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


# ---------------------------------------------------------------------------
# Templates API Endpoints
# ---------------------------------------------------------------------------


@app.get("/templates", tags=["templates"])
async def list_templates():
    return await storage.get_templates()


@app.get("/templates/{template_id}", tags=["templates"])
async def get_template(template_id: UUID):
    tmpl = await storage.get_template_by_id(template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tmpl


class TemplateCreateRequest(BaseModel):
    name: str
    target_type: str = "all"
    description: Optional[str] = None
    subject: Optional[str] = None
    body: str


@app.post("/templates", tags=["templates"])
async def create_template(body: TemplateCreateRequest):
    if not body.name.strip() or not body.body.strip():
        raise HTTPException(status_code=400, detail="Name and body are required")

    # Validate Jinja2 syntax
    try:
        Template(body.body)
    except TemplateSyntaxError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Jinja2 syntax on line {exc.lineno}: {exc.message}",
        )

    try:
        created = await storage.create_template(
            name=body.name.strip(),
            target_type=body.target_type,
            body=body.body,
            description=body.description.strip() if body.description else None,
            subject=body.subject.strip() if body.subject else None,
        )
        return created
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to create template: {exc}")


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    target_type: Optional[str] = None
    description: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    is_active: Optional[bool] = None


@app.put("/templates/{template_id}", tags=["templates"])
async def update_template(template_id: UUID, body: TemplateUpdateRequest):
    if body.body is not None:
        try:
            Template(body.body)
        except TemplateSyntaxError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid Jinja2 syntax on line {exc.lineno}: {exc.message}",
            )

    try:
        updated = await storage.update_template(
            template_id=template_id,
            name=body.name,
            target_type=body.target_type,
            description=body.description,
            body=body.body,
            subject=body.subject,
            is_active=body.is_active,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Template not found")
        return updated
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to update template: {exc}")


@app.delete("/templates/{template_id}", tags=["templates"])
async def delete_template(template_id: UUID):
    try:
        deleted = await storage.delete_template(template_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Template not found")
        return {"message": "Template deleted successfully"}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class StandalonePreviewRequest(BaseModel):
    template_body: str
    first_name: Optional[str] = "Priya"
    company: Optional[str] = "Zepto"
    their_role: Optional[str] = "Engineering Manager"
    contact_type: Optional[str] = "technical"


@app.post("/templates/preview", tags=["templates"])
async def preview_template_standalone(body: StandalonePreviewRequest):
    if not body.template_body or not body.template_body.strip():
        raise HTTPException(status_code=400, detail="template_body is required")

    profile = get_candidate_profile()
    context = {
        "first_name": (body.first_name or "Priya").strip(),
        "company": (body.company or "Zepto").strip(),
        "their_role": (body.their_role or "Engineering Manager").strip(),
        "contact_type": body.contact_type or "technical",
        "profile": profile,
    }

    try:
        tmpl = Template(body.template_body)
        rendered = tmpl.render(**context)
        return {"rendered": rendered}
    except TemplateSyntaxError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Jinja2 Syntax Error line {exc.lineno}: {exc.message}",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Preview rendering failed: {exc}")


class TemplatePreviewRequest(BaseModel):
    first_name: Optional[str] = "Priya"
    company: Optional[str] = "Zepto"
    their_role: Optional[str] = "Engineering Manager"
    contact_type: Optional[str] = "technical"


@app.post("/templates/{template_id}/preview", tags=["templates"])
async def preview_template_by_id(template_id: UUID, body: TemplatePreviewRequest):
    tmpl_obj = await storage.get_template_by_id(template_id)
    if not tmpl_obj:
        raise HTTPException(status_code=404, detail="Template not found")

    profile = get_candidate_profile()
    context = {
        "first_name": (body.first_name or "Priya").strip(),
        "company": (body.company or "Zepto").strip(),
        "their_role": (body.their_role or "Engineering Manager").strip(),
        "contact_type": body.contact_type or tmpl_obj.get("target_type", "all"),
        "profile": profile,
    }

    try:
        tmpl = Template(tmpl_obj["body"])
        rendered = tmpl.render(**context)
        return {"rendered": rendered}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Rendering failed: {exc}")


class TemplateApplyRequest(BaseModel):
    contact_type: Optional[str] = None


@app.post("/templates/{template_id}/apply", tags=["templates"])
async def apply_template(template_id: UUID, body: TemplateApplyRequest):
    tmpl_obj = await storage.get_template_by_id(template_id)
    if not tmpl_obj:
        raise HTTPException(status_code=404, detail="Template not found")

    target_type = body.contact_type or tmpl_obj.get("target_type", "all")

    contacts, total = await storage.get_contacts(
        contact_type=target_type, status="all", limit=5000, offset=0
    )

    updated_count = 0
    for c in contacts:
        draft, t_used = await render_draft(
            contact_type=c["contact_type"],
            first_name=c["first_name"],
            company=c["company"],
            position=c["position"],
            override_template_body=tmpl_obj["body"],
        )
        await storage.update_contact_draft(
            c["id"], draft, tmpl_obj.get("name", "custom_template")
        )
        updated_count += 1

    return {"updated": updated_count}


# ---------------------------------------------------------------------------
# Import Endpoint (CSV + Excel support)
# ---------------------------------------------------------------------------


def parse_csv_bytes(content: bytes) -> List[Dict[str, str]]:
    text = content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if len(lines) < 4:
        raise HTTPException(
            status_code=400,
            detail="CSV file must have at least 4 lines (3 notes/header lines + data)",
        )
    csv_data_lines = lines[3:]
    reader = csv.DictReader(csv_data_lines)
    return [row for row in reader]


def parse_excel_bytes(content: bytes) -> List[Dict[str, str]]:
    wb = openpyxl.load_workbook(filename=io.BytesIO(content), data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))

    header_row_idx = None
    header_keys = []

    for idx, row in enumerate(rows):
        row_str_vals = [str(val).strip() if val is not None else "" for val in row]
        if any("first name" in val.lower() for val in row_str_vals):
            header_row_idx = idx
            header_keys = row_str_vals
            break

    if header_row_idx is None:
        raise HTTPException(
            status_code=400,
            detail="Could not locate header row containing 'First Name' in Excel sheet.",
        )

    parsed_data = []
    for row in rows[header_row_idx + 1 :]:
        row_dict = {}
        for col_idx, cell_val in enumerate(row):
            if col_idx < len(header_keys) and header_keys[col_idx]:
                key = header_keys[col_idx]
                row_dict[key] = str(cell_val).strip() if cell_val is not None else ""
        if any(row_dict.values()):
            parsed_data.append(row_dict)

    return parsed_data


@app.post("/import", tags=["import"])
async def import_connections(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith((".csv", ".xlsx", ".xls")):
        return JSONResponse(
            status_code=400,
            content={"error": "Unsupported file format. Upload a .csv or .xlsx file."},
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=400,
            content={"error": "File size exceeds 10MB limit."},
        )

    try:
        if filename.endswith(".csv"):
            raw_rows = parse_csv_bytes(content)
        else:
            raw_rows = parse_excel_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    contacts_to_insert = []
    for row in raw_rows:
        # Match case-insensitive keys in dict
        key_map = {str(k).strip().lower(): v for k, v in row.items() if k}

        url = (key_map.get("url") or key_map.get("linkedin url") or "").strip()
        if not url:
            continue

        first_name = (key_map.get("first name") or "").strip()
        last_name = (key_map.get("last name") or "").strip()
        email = (key_map.get("email address") or key_map.get("email") or "").strip()
        company = (key_map.get("company") or "").strip()
        position = (key_map.get("position") or key_map.get("job title") or "").strip()
        connected_on = (key_map.get("connected on") or "").strip()

        ctype = classify_position(position)
        draft, template_used = await render_draft(ctype, first_name, company, position)

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


# ---------------------------------------------------------------------------
# Contacts API Endpoints
# ---------------------------------------------------------------------------


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

    draft, template_used = await render_draft(
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
