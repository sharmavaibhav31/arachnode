"""
storage.py — asyncpg pool, emails table DDL, and CRUD helpers
for the Cold Email Generator Service.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
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
    logger.info("PostgreSQL pool ready (email-generator).")
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised — call create_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Referenced tables (idempotent guards so this service can stand alone)
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

CREATE TABLE IF NOT EXISTS emails (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id       UUID        REFERENCES jobs(id) ON DELETE SET NULL,
    contact_id   UUID        REFERENCES contacts(id) ON DELETE SET NULL,
    template     TEXT        NOT NULL,
    subject      TEXT        NOT NULL,
    body         TEXT        NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at      TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'draft'
);

CREATE INDEX IF NOT EXISTS idx_emails_job_id
    ON emails (job_id) WHERE job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_emails_contact_id
    ON emails (contact_id) WHERE contact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_emails_status
    ON emails (status);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
    logger.info("emails schema verified / created.")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def insert_email(
    pool: asyncpg.Pool,
    *,
    job_id: Optional[UUID],
    contact_id: Optional[UUID],
    template: str,
    subject: str,
    body: str,
) -> asyncpg.Record:
    sql = """
        INSERT INTO emails (job_id, contact_id, template, subject, body)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, job_id, contact_id, template, subject, body)


async def get_email_by_id(pool: asyncpg.Pool, email_id: UUID) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM emails WHERE id = $1", email_id)


async def get_emails_by_job(pool: asyncpg.Pool, job_id: UUID) -> list:
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM emails WHERE job_id = $1 ORDER BY generated_at DESC",
            job_id,
        )


async def update_status(
    pool: asyncpg.Pool, email_id: UUID, status: str
) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "UPDATE emails SET status = $1 WHERE id = $2 RETURNING *",
            status, email_id,
        )


async def mark_sent(pool: asyncpg.Pool, email_id: UUID) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            """UPDATE emails
               SET status = 'sent', sent_at = NOW()
               WHERE id = $1
               RETURNING *""",
            email_id,
        )


async def get_job_by_id(pool: asyncpg.Pool, job_id: UUID) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
    if row:
        d = dict(row)
        d["url"] = crypt.decrypt_url(d.get("url"))
        return d
    return None


async def get_contact_by_id(
    pool: asyncpg.Pool, contact_id: UUID
) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM contacts WHERE id = $1", contact_id)
