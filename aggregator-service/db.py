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

_pool: Optional[asyncpg.Pool] = None


async def create_pool() -> asyncpg.Pool:
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

CREATE INDEX IF NOT EXISTS idx_jobs_stack
    ON jobs USING GIN (stack);

CREATE INDEX IF NOT EXISTS idx_jobs_posted_at
    ON jobs (posted_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs (status);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    logger.info("Database schema verified / created.")


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
    posted_at: Optional[Any],
) -> Optional[asyncpg.Record]:
    sql = """
        INSERT INTO jobs (company, role, source, url, stack, product, location, posted_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, COALESCE($8, NOW()))
        ON CONFLICT DO NOTHING
        RETURNING *
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql, company, role, source, url, stack, product, location, posted_at
        )
    return row

def _build_job_filters(
    role: Optional[str] = None,
    stack: Optional[List[str]] = None,
    status: Optional[str] = None,
):
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
    return where_clause, params, idx

async def get_jobs_count(
    pool: asyncpg.Pool,
    *,
    role: Optional[str] = None,
    stack: Optional[List[str]] = None,
    status: Optional[str] = None,
) -> int:
    where_clause, params, _ = _build_job_filters(role, stack, status)
    sql = f"SELECT COUNT(*) FROM jobs {where_clause}"
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *params)


async def get_jobs(
    pool: asyncpg.Pool,
    *,
    role: Optional[str] = None,
    stack: Optional[List[str]] = None,
    status: Optional[str] = None,
    sort: str = "latest",
    limit: int = 50,
    offset: int = 0,
) -> List[asyncpg.Record]:
    where_clause, params, idx = _build_job_filters(role, stack, status)
    order = "DESC NULLS LAST" if sort == "latest" else "ASC NULLS LAST"

    params.append(limit)
    limit_idx = idx
    idx += 1
    
    params.append(offset)
    offset_idx = idx

    sql = f"""
        SELECT * FROM jobs
        {where_clause}
        ORDER BY posted_at {order}
        LIMIT ${limit_idx} OFFSET ${offset_idx}
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


async def get_stats(pool: asyncpg.Pool, days: int = 30) -> Dict[str, Any]:
    sql_source = f"""
        SELECT COALESCE(source, 'unknown') AS key, COUNT(*) AS cnt
        FROM jobs
        WHERE created_at >= NOW() - INTERVAL '{days} days'
        GROUP BY source
    """
    sql_status = f"""
        SELECT status AS key, COUNT(*) AS cnt
        FROM jobs
        WHERE created_at >= NOW() - INTERVAL '{days} days'
        GROUP BY status
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
    where_clause, params, _ = _build_job_filters(role, stack, status)
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
