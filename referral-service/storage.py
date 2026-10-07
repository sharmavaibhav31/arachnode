"""
storage.py — PostgreSQL persistence helper for Referral Service.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import date as date_type, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

TEMPLATES_DIR = Path(__file__).parent / "templates"


async def create_pool() -> asyncpg.Pool:
    global _pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.warning("DATABASE_URL not set for storage.py")
        return None
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await _init_schema(_pool)
    await _seed_system_templates(_pool)
    logger.info("Referral Service PostgreSQL pool ready.")
    return _pool


async def get_pool() -> Optional[asyncpg.Pool]:
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Referral Service PostgreSQL pool closed.")


_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS referral_contacts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name      TEXT NOT NULL,
  last_name       TEXT,
  linkedin_url    TEXT NOT NULL UNIQUE,
  email           TEXT,
  company         TEXT,
  position        TEXT,
  connected_on    TEXT,
  contact_type    TEXT NOT NULL DEFAULT 'unknown',
                  -- hr | technical | leadership | other | unknown
  status          TEXT NOT NULL DEFAULT 'pending',
                  -- pending | queued | sent | replied | skipped
  message_draft   TEXT,
  template_used   TEXT,
  queued_for_date DATE,
  sent_at         TIMESTAMPTZ,
  notes           TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_referral_status 
  ON referral_contacts(status);
CREATE INDEX IF NOT EXISTS idx_referral_type 
  ON referral_contacts(contact_type);
CREATE INDEX IF NOT EXISTS idx_referral_queued_date 
  ON referral_contacts(queued_for_date);

CREATE TABLE IF NOT EXISTS referral_templates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT NOT NULL UNIQUE,
  description  TEXT,
  target_type  TEXT NOT NULL DEFAULT 'all',
               -- hr|technical|leadership|other|unknown|all
  subject      TEXT,         -- for future email use
  body         TEXT NOT NULL, -- Jinja2 template string
  is_system    BOOLEAN NOT NULL DEFAULT false,
               -- true = built-in, cannot be deleted
  is_active    BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    logger.info("Referral contacts and templates schema verified/created.")


SYSTEM_TEMPLATES_SEED = [
    ("System HR Template", "hr", "hr_outreach.j2", "System template for HR and Talent Acquisition"),
    ("System Technical Template", "technical", "technical_outreach.j2", "System template for Engineers and Technical roles"),
    ("System Leadership Template", "leadership", "leadership_outreach.j2", "System template for Founders, Directors, and VPs"),
    ("System Other Template", "other", "other_outreach.j2", "System template for Analysts, Consultants, and other roles"),
    ("System Unknown Template", "unknown", "unknown_outreach.j2", "System template for contacts with no position listed"),
]


async def _seed_system_templates(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        for name, target_type, file_name, desc in SYSTEM_TEMPLATES_SEED:
            tmpl_path = TEMPLATES_DIR / file_name
            if tmpl_path.exists():
                try:
                    body = tmpl_path.read_text(encoding="utf-8")
                    await conn.execute(
                        """
                        INSERT INTO referral_templates (name, description, target_type, body, is_system, is_active)
                        VALUES ($1, $2, $3, $4, true, true)
                        ON CONFLICT (name) DO UPDATE
                        SET body = EXCLUDED.body,
                            description = EXCLUDED.description,
                            updated_at = NOW()
                        """,
                        name,
                        desc,
                        target_type,
                        body,
                    )
                except Exception as exc:
                    logger.error(f"Failed to seed template {name}: {exc}")


def _format_record(row) -> Dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, (datetime, date_type)):
            d[k] = v.isoformat()
    return d


# ---------------------------------------------------------------------------
# Templates CRUD
# ---------------------------------------------------------------------------


async def get_templates() -> List[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return []

    sql = """
        SELECT id, name, description, target_type, subject, is_system, is_active, created_at, updated_at
        FROM referral_templates
        ORDER BY is_system DESC, name ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
        return [_format_record(r) for r in rows]


async def get_template_by_id(template_id: str | UUID) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    tid = UUID(str(template_id)) if isinstance(template_id, str) else template_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM referral_templates WHERE id = $1", tid)
        return _format_record(row) if row else None


async def create_template(
    name: str,
    target_type: str,
    body: str,
    description: Optional[str] = None,
    subject: Optional[str] = None,
) -> Dict[str, Any]:
    pool = await get_pool()
    if not pool:
        raise RuntimeError("Database pool not initialized")

    sql = """
        INSERT INTO referral_templates (name, description, target_type, body, subject, is_system, is_active)
        VALUES ($1, $2, $3, $4, $5, false, true)
        RETURNING *
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, name, description, target_type.lower(), body, subject)
        return _format_record(row)


async def update_template(
    template_id: str | UUID,
    name: Optional[str] = None,
    description: Optional[str] = None,
    target_type: Optional[str] = None,
    body: Optional[str] = None,
    subject: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    tid = UUID(str(template_id)) if isinstance(template_id, str) else template_id

    existing = await get_template_by_id(tid)
    if not existing:
        return None
    if existing.get("is_system"):
        raise PermissionError("System templates cannot be edited via API")

    updates = []
    params: List[Any] = [tid]
    param_idx = 2

    if name is not None:
        updates.append(f"name = ${param_idx}")
        params.append(name)
        param_idx += 1
    if description is not None:
        updates.append(f"description = ${param_idx}")
        params.append(description)
        param_idx += 1
    if target_type is not None:
        updates.append(f"target_type = ${param_idx}")
        params.append(target_type.lower())
        param_idx += 1
    if body is not None:
        updates.append(f"body = ${param_idx}")
        params.append(body)
        param_idx += 1
    if subject is not None:
        updates.append(f"subject = ${param_idx}")
        params.append(subject)
        param_idx += 1
    if is_active is not None:
        updates.append(f"is_active = ${param_idx}")
        params.append(is_active)
        param_idx += 1

    if not updates:
        return existing

    updates.append("updated_at = NOW()")
    sql = f"UPDATE referral_templates SET {', '.join(updates)} WHERE id = $1 RETURNING *"

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
        return _format_record(row) if row else None


async def delete_template(template_id: str | UUID) -> bool:
    pool = await get_pool()
    if not pool:
        return False

    tid = UUID(str(template_id)) if isinstance(template_id, str) else template_id
    existing = await get_template_by_id(tid)
    if not existing:
        return False
    if existing.get("is_system"):
        raise PermissionError("System templates cannot be deleted")

    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM referral_templates WHERE id = $1", tid)
        return res.endswith("1")


async def get_active_template_for_type(contact_type: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    ctype = contact_type.lower()

    async with pool.acquire() as conn:
        # Priority 1: Active custom template matching contact_type
        row = await conn.fetchrow(
            """
            SELECT * FROM referral_templates
            WHERE target_type = $1 AND is_active = true AND is_system = false
            ORDER BY created_at DESC LIMIT 1
            """,
            ctype,
        )
        if row:
            return _format_record(row)

        # Priority 2: Active custom template with target_type = 'all'
        row = await conn.fetchrow(
            """
            SELECT * FROM referral_templates
            WHERE target_type = 'all' AND is_active = true AND is_system = false
            ORDER BY created_at DESC LIMIT 1
            """
        )
        if row:
            return _format_record(row)

        # Priority 3: System template matching contact_type
        row = await conn.fetchrow(
            """
            SELECT * FROM referral_templates
            WHERE target_type = $1 AND is_system = true AND is_active = true
            LIMIT 1
            """,
            ctype,
        )
        if row:
            return _format_record(row)

        # Priority 4: System template matching 'other' or 'unknown'
        row = await conn.fetchrow(
            """
            SELECT * FROM referral_templates
            WHERE is_system = true AND is_active = true
            ORDER BY created_at ASC LIMIT 1
            """
        )
        return _format_record(row) if row else None


# ---------------------------------------------------------------------------
# Contacts persistence
# ---------------------------------------------------------------------------


async def import_contacts(contacts_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    pool = await get_pool()
    if not pool:
        raise RuntimeError("Database pool not initialized")

    imported_count = 0
    skipped_count = 0
    by_type = {"hr": 0, "technical": 0, "leadership": 0, "other": 0, "unknown": 0}

    insert_sql = """
        INSERT INTO referral_contacts (
            first_name, last_name, linkedin_url, email, company, position,
            connected_on, contact_type, status, message_draft, template_used
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (linkedin_url) DO NOTHING
        RETURNING contact_type
    """

    async with pool.acquire() as conn:
        for c in contacts_data:
            row = await conn.fetchrow(
                insert_sql,
                c["first_name"],
                c.get("last_name"),
                c["linkedin_url"],
                c.get("email"),
                c.get("company"),
                c.get("position"),
                c.get("connected_on"),
                c.get("contact_type", "unknown"),
                c.get("status", "pending"),
                c.get("message_draft"),
                c.get("template_used"),
            )
            if row:
                imported_count += 1
                ctype = row["contact_type"]
                by_type[ctype] = by_type.get(ctype, 0) + 1
            else:
                skipped_count += 1

    return {
        "imported": imported_count,
        "skipped_duplicates": skipped_count,
        "by_type": by_type,
    }


async def get_contacts(
    contact_type: str = "all",
    status: str = "all",
    limit: int = 50,
    offset: int = 0,
    company: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    pool = await get_pool()
    if not pool:
        return [], 0

    where_clauses = []
    params: List[Any] = []
    param_idx = 1

    if contact_type and contact_type.lower() != "all":
        where_clauses.append(f"contact_type = ${param_idx}")
        params.append(contact_type.lower())
        param_idx += 1

    if status and status.lower() != "all":
        where_clauses.append(f"status = ${param_idx}")
        params.append(status.lower())
        param_idx += 1

    if company and company.strip():
        where_clauses.append(f"company ILIKE ${param_idx}")
        params.append(f"%{company.strip()}%")
        param_idx += 1

    where_str = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_query = f"SELECT COUNT(*) FROM referral_contacts{where_str}"

    fetch_query = f"""
        SELECT * FROM referral_contacts
        {where_str}
        ORDER BY created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
    """

    async with pool.acquire() as conn:
        total = await conn.fetchval(count_query, *params)
        fetch_params = params + [limit, offset]
        rows = await conn.fetch(fetch_query, *fetch_params)

    return [_format_record(r) for r in rows], total


async def get_contact_by_id(contact_id: str | UUID) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    cid = UUID(str(contact_id)) if isinstance(contact_id, str) else contact_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM referral_contacts WHERE id = $1", cid)
        return _format_record(row) if row else None


async def update_contact(
    contact_id: str | UUID,
    status: Optional[str] = None,
    notes: Optional[str] = None,
    message_draft: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    cid = UUID(str(contact_id)) if isinstance(contact_id, str) else contact_id

    updates = []
    params: List[Any] = [cid]
    param_idx = 2

    if status is not None:
        updates.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
        if status == "sent":
            updates.append("sent_at = NOW()")

    if notes is not None:
        updates.append(f"notes = ${param_idx}")
        params.append(notes)
        param_idx += 1

    if message_draft is not None:
        updates.append(f"message_draft = ${param_idx}")
        params.append(message_draft)
        param_idx += 1

    if not updates:
        return await get_contact_by_id(cid)

    updates.append("updated_at = NOW()")
    sql = f"""
        UPDATE referral_contacts
        SET {', '.join(updates)}
        WHERE id = $1
        RETURNING *
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
        return _format_record(row) if row else None


async def update_contact_draft(
    contact_id: str | UUID,
    message_draft: str,
    template_used: str,
) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None

    cid = UUID(str(contact_id)) if isinstance(contact_id, str) else contact_id
    sql = """
        UPDATE referral_contacts
        SET message_draft = $2, template_used = $3, updated_at = NOW()
        WHERE id = $1
        RETURNING *
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, cid, message_draft, template_used)
        return _format_record(row) if row else None


async def get_queue_for_date(target_date: str) -> List[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return []

    sql = """
        SELECT * FROM referral_contacts
        WHERE queued_for_date = $1::date
        ORDER BY CASE contact_type
            WHEN 'hr' THEN 1
            WHEN 'leadership' THEN 2
            WHEN 'technical' THEN 3
            WHEN 'other' THEN 4
            ELSE 5
        END, created_at ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, target_date)
        return [_format_record(r) for r in rows]


async def generate_queue(
    target_date: str,
    count: int = 12,
    prefer_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return []

    capped_count = min(max(count, 1), 15)

    case_whens = []
    order_idx = 1
    if prefer_types:
        for ptype in prefer_types:
            case_whens.append(f"WHEN '{ptype.lower()}' THEN {order_idx}")
            order_idx += 1

    default_types = ["hr", "leadership", "technical", "other", "unknown"]
    for dtype in default_types:
        if not prefer_types or dtype not in [pt.lower() for pt in prefer_types]:
            case_whens.append(f"WHEN '{dtype}' THEN {order_idx}")
            order_idx += 1

    case_sql = "CASE contact_type " + " ".join(case_whens) + " ELSE 99 END"

    update_sql = f"""
        WITH to_queue AS (
            SELECT id FROM referral_contacts
            WHERE status = 'pending' AND queued_for_date IS NULL
            ORDER BY {case_sql}, created_at ASC
            LIMIT $1
        )
        UPDATE referral_contacts
        SET status = 'queued',
            queued_for_date = $2::date,
            updated_at = NOW()
        WHERE id IN (SELECT id FROM to_queue)
    """

    async with pool.acquire() as conn:
        await conn.execute(update_sql, capped_count, target_date)

    return await get_queue_for_date(target_date)


async def mark_contacts_sent(contact_ids: List[str | UUID]) -> int:
    pool = await get_pool()
    if not pool:
        return 0

    uuids = [UUID(str(cid)) if isinstance(cid, str) else cid for cid in contact_ids]

    sql = """
        UPDATE referral_contacts
        SET status = 'sent',
            sent_at = NOW(),
            updated_at = NOW()
        WHERE id = ANY($1::uuid[])
    """
    async with pool.acquire() as conn:
        res = await conn.execute(sql, uuids)
        try:
            return int(res.split(" ")[1])
        except Exception:
            return len(uuids)


async def get_stats() -> Dict[str, Any]:
    pool = await get_pool()
    daily_limit = int(os.environ.get("REFERRAL_DAILY_LIMIT", "12"))

    if not pool:
        return {
            "total": 0,
            "by_type": {"hr": 0, "technical": 0, "leadership": 0, "other": 0, "unknown": 0},
            "by_status": {"pending": 0, "queued": 0, "sent": 0, "replied": 0, "skipped": 0},
            "sent_today": 0,
            "queued_today": 0,
            "daily_remaining": daily_limit,
            "estimated_days_remaining": 0,
        }

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM referral_contacts") or 0

        type_rows = await conn.fetch("SELECT contact_type, COUNT(*) as cnt FROM referral_contacts GROUP BY contact_type")
        by_type = {"hr": 0, "technical": 0, "leadership": 0, "other": 0, "unknown": 0}
        for r in type_rows:
            by_type[r["contact_type"]] = r["cnt"]

        status_rows = await conn.fetch("SELECT status, COUNT(*) as cnt FROM referral_contacts GROUP BY status")
        by_status = {"pending": 0, "queued": 0, "sent": 0, "replied": 0, "skipped": 0}
        for r in status_rows:
            by_status[r["status"]] = r["cnt"]

        sent_today = await conn.fetchval(
            "SELECT COUNT(*) FROM referral_contacts WHERE status = 'sent' AND (sent_at AT TIME ZONE 'UTC')::date = CURRENT_DATE"
        ) or 0

        queued_today = await conn.fetchval(
            "SELECT COUNT(*) FROM referral_contacts WHERE queued_for_date = CURRENT_DATE"
        ) or 0

    daily_remaining = max(0, daily_limit - sent_today)
    pending_cnt = by_status.get("pending", 0)
    est_days = math.ceil(pending_cnt / daily_limit) if daily_limit > 0 else 0

    return {
        "total": total,
        "by_type": by_type,
        "by_status": by_status,
        "sent_today": sent_today,
        "queued_today": queued_today,
        "daily_remaining": daily_remaining,
        "estimated_days_remaining": est_days,
    }
