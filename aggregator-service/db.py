"""
db.py — asyncpg connection pool, schema initialisation, and query helpers.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
    """Create the global asyncpg connection pool and initialise the schema."""
    global _pool
    database_url = os.environ["DATABASE_URL"]
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await _init_schema(_pool)
    logger.info("PostgreSQL pool ready.")
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
        logger.info("PostgreSQL pool closed.")


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS jobs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company     TEXT        NOT NULL,
    role        TEXT        NOT NULL,
    source      TEXT,
    url         TEXT,
    stack       TEXT[],
    product     TEXT,
    location    TEXT,
    posted_at   TIMESTAMPTZ,
    status      TEXT        NOT NULL DEFAULT 'new',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GIN index for fast array containment queries on stack
CREATE INDEX IF NOT EXISTS idx_jobs_stack
    ON jobs USING GIN (stack);

-- BTREE index for sorting / filtering by posted date
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at
    ON jobs (posted_at DESC NULLS LAST);

-- BTREE index for filtering by status
CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    """Run schema DDL idempotently on startup."""
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    logger.info("Database schema verified / created.")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def insert_job(
    pool: asyncpg.Pool,
    *,
    company: str,
    role: str,
    source: Optional[str],
    url: Optional[str],
    stack: Optional[List[str]],
    product: Optional[str],
    location: Optional[str],
    posted_at: Optional[Any],  # datetime or None
) -> Optional[asyncpg.Record]:
    """
    Insert a new job row.  Returns the inserted record, or None on conflict.
    Uses INSERT … ON CONFLICT DO NOTHING so duplicate URLs are silently dropped.
    """
    sql = """
        INSERT INTO jobs (company, role, source, url, stack, product, location, posted_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT DO NOTHING
        RETURNING *
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql, company, role, source, url, stack, product, location, posted_at
        )
    return row


async def get_jobs(
    pool: asyncpg.Pool,
    *,
    role: Optional[str] = None,
    stack: Optional[List[str]] = None,
    status: Optional[str] = None,
    sort: str = "latest",
    limit: int = 50,
) -> List[asyncpg.Record]:
    """
    Fetch jobs with optional filters and sorting.

    - role   : case-insensitive substring match
    - stack  : jobs whose stack contains ALL supplied tags
    - status : exact match
    - sort   : 'latest' → posted_at DESC, 'oldest' → posted_at ASC
    """
    conditions: List[str] = []
    params: List[Any] = []
    idx = 1

    if role:
        conditions.append(f"role ILIKE ${idx}")
        params.append(f"%{role}%")
        idx += 1

    if stack:
        conditions.append(f"stack @> ${idx}::text[]")
        params.append(stack)
        idx += 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = "DESC NULLS LAST" if sort == "latest" else "ASC NULLS LAST"

    params.append(limit)
    sql = f"""
        SELECT * FROM jobs
        {where_clause}
        ORDER BY posted_at {order}
        LIMIT ${idx}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return rows


async def get_job_by_id(pool: asyncpg.Pool, job_id: UUID) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)


async def update_job_status(
    pool: asyncpg.Pool, job_id: UUID, status: str
) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "UPDATE jobs SET status = $1 WHERE id = $2 RETURNING *",
            status,
            job_id,
        )


async def get_stats(pool: asyncpg.Pool) -> Dict[str, Any]:
    """Return count by source and count by status."""
    sql_source = """
        SELECT COALESCE(source, 'unknown') AS key, COUNT(*) AS cnt
        FROM jobs GROUP BY source
    """
    sql_status = """
        SELECT status AS key, COUNT(*) AS cnt
        FROM jobs GROUP BY status
    """
    async with pool.acquire() as conn:
        source_rows = await conn.fetch(sql_source)
        status_rows = await conn.fetch(sql_status)

    return {
        "by_source": {r["key"]: r["cnt"] for r in source_rows},
        "by_status": {r["key"]: r["cnt"] for r in status_rows},
    }


async def stream_jobs(
    pool: asyncpg.Pool,
    *,
    role: Optional[str] = None,
    stack: Optional[List[str]] = None,
    status: Optional[str] = None,
    sort: str = "latest",
):
    """
    Stream jobs with optional filters and sorting using server-side cursor.

    Yields chunks of records. Use inside a transaction for cursor stability.
    """
    conditions: List[str] = []
    params: List[Any] = []
    idx = 1

    if role:
        conditions.append(f"role ILIKE ${idx}")
        params.append(f"%{role}%")
        idx += 1

    if stack:
        conditions.append(f"stack @> ${idx}::text[]")
        params.append(stack)
        idx += 1

    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = "DESC NULLS LAST" if sort == "latest" else "ASC NULLS LAST"

    sql = f"""
        SELECT * FROM jobs
        {where_clause}
        ORDER BY posted_at {order}
    """

    async with pool.acquire() as conn:
        async with conn.transaction():
            async for record in conn.cursor(sql, *params, prefetch=1000):
                yield record
