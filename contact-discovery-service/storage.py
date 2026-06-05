"""
storage.py — asyncpg schema init and CRUD helpers for the Contact Discovery Service.

Shares the same PostgreSQL instance as the Job Aggregator Service,
adding a new `contacts` table that optionally references `jobs(id)`.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

import crypt

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

async def create_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"],
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await _init_schema(_pool)
    logger.info("PostgreSQL pool ready (contact-discovery).")
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised. Call create_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Ensure the jobs table exists so the FK is valid.
-- (It will already exist if the aggregator ran first; this is safe.)
CREATE TABLE IF NOT EXISTS jobs (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company    TEXT        NOT NULL,
    role       TEXT        NOT NULL,
    source     TEXT,
    url        TEXT,
    stack      TEXT[],
    product    TEXT,
    location   TEXT,
    posted_at  TIMESTAMPTZ,
    status     TEXT        NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     UUID        REFERENCES jobs(id) ON DELETE SET NULL,
    company    TEXT        NOT NULL,
    domain     TEXT,
    name       TEXT,
    email      TEXT,
    role       TEXT,
    source     TEXT,
    verified   TEXT        NOT NULL DEFAULT 'unverified',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contacts_company
    ON contacts (company);

CREATE INDEX IF NOT EXISTS idx_contacts_job_id
    ON contacts (job_id)
    WHERE job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
    logger.info("contacts schema verified / created.")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def upsert_contact(
    pool: asyncpg.Pool,
    *,
    job_id: Optional[UUID],
    company: str,
    domain: Optional[str],
    name: Optional[str],
    email: Optional[str],
    role: Optional[str],
    source: Optional[str],
    verified: str = "unverified",
) -> asyncpg.Record:
    """
    Insert or update a contact.  Uniqueness is (company, email) — if the same
    email was already discovered for a company, the verified status and role
    are refreshed rather than creating a duplicate row.
    """
    sql = """
        INSERT INTO contacts
               (job_id, company, domain, name, email, role, source, verified)
        VALUES ($1,     $2,      $3,     $4,   $5,    $6,   $7,     $8)
        ON CONFLICT (company, email)
        DO UPDATE SET
            verified   = EXCLUDED.verified,
            role       = COALESCE(EXCLUDED.role, contacts.role),
            name       = COALESCE(EXCLUDED.name, contacts.name),
            source     = EXCLUDED.source
        RETURNING *
    """
    # Ensure the unique constraint exists (idempotent)
    await _ensure_unique_constraint(pool)
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            sql, job_id, company, domain, name, email, role, source, verified
        )


async def _ensure_unique_constraint(pool: asyncpg.Pool) -> None:
    """Add unique constraint on (company, email) if it doesn't exist yet."""
    check = """
        SELECT 1 FROM pg_constraint
        WHERE conname = 'contacts_company_email_key'
    """
    create = """
        ALTER TABLE contacts
        ADD CONSTRAINT contacts_company_email_key UNIQUE (company, email)
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(check)
        if not row:
            try:
                await conn.execute(create)
            except asyncpg.DuplicateTableError:
                pass  # race condition; another instance added it first


async def insert_contact_simple(
    pool: asyncpg.Pool,
    *,
    job_id: Optional[UUID],
    company: str,
    domain: Optional[str],
    name: Optional[str],
    email: Optional[str],
    role: Optional[str],
    source: Optional[str],
    verified: str = "unverified",
) -> asyncpg.Record:
    """Plain INSERT RETURNING — use upsert_contact when email uniqueness matters."""
    sql = """
        INSERT INTO contacts
               (job_id, company, domain, name, email, role, source, verified)
        VALUES ($1,     $2,      $3,     $4,   $5,    $6,   $7,     $8)
        RETURNING *
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            sql, job_id, company, domain, name, email, role, source, verified
        )


async def get_contacts_by_company(
    pool: asyncpg.Pool, company: str
) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM contacts WHERE company ILIKE $1 ORDER BY created_at DESC",
            f"%{company}%",
        )


async def get_contacts_by_job(
    pool: asyncpg.Pool, job_id: UUID
) -> List[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM contacts WHERE job_id = $1 ORDER BY created_at DESC",
            job_id,
        )


async def delete_contact(pool: asyncpg.Pool, contact_id: UUID) -> bool:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM contacts WHERE id = $1", contact_id
        )
    return result.endswith("1")
