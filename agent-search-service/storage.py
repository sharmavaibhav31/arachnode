"""
storage.py — PostgreSQL connection pool, schema management, and persistence helpers.

Manages tables agent_searches and agent_search_results via asyncpg.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
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
    logger.info("PostgreSQL pool ready in agent-search-service.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call create_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed in agent-search-service.")


_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS agent_searches (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  query        TEXT NOT NULL,
  parsed_intent JSONB,
  filters      JSONB,
  results_count INTEGER DEFAULT 0,
  stale_count  INTEGER DEFAULT 0,
  status       TEXT DEFAULT 'running',
  provider_used TEXT,
  duration_ms  INTEGER,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_search_results (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  search_id    UUID REFERENCES agent_searches(id) ON DELETE CASCADE,
  company      TEXT,
  role         TEXT,
  stack        TEXT[],
  location     TEXT,
  posted_at    TIMESTAMPTZ,
  date_unknown BOOLEAN DEFAULT false,
  relevance_score FLOAT,
  url          TEXT,
  source       TEXT,
  saved_to_pipeline BOOLEAN DEFAULT false,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_searches_created ON agent_searches(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_results_search_id ON agent_search_results(search_id);
CREATE INDEX IF NOT EXISTS idx_search_results_posted_at ON agent_search_results(posted_at DESC NULLS LAST);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    logger.info("Agent search schema verified / created.")


async def create_search(query: str, filters: Dict[str, Any], provider_used: Optional[str] = None) -> str:
    pool = await get_pool()
    sql = """
        INSERT INTO agent_searches (query, filters, provider_used, status)
        VALUES ($1, $2::jsonb, $3, 'running')
        RETURNING id
    """
    async with pool.acquire() as conn:
        search_id = await conn.fetchval(sql, query, json.dumps(filters), provider_used)
    return str(search_id)


async def get_search(search_id: str | UUID) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    sql = "SELECT * FROM agent_searches WHERE id = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, UUID(str(search_id)))
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    if d.get("parsed_intent") and isinstance(d["parsed_intent"], str):
        d["parsed_intent"] = json.loads(d["parsed_intent"])
    if d.get("filters") and isinstance(d["filters"], str):
        d["filters"] = json.loads(d["filters"])
    return d


async def update_search(
    search_id: str | UUID,
    parsed_intent: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
) -> None:
    pool = await get_pool()
    updates = []
    params: List[Any] = [UUID(str(search_id))]
    idx = 2

    if parsed_intent is not None:
        updates.append(f"parsed_intent = ${idx}::jsonb")
        params.append(json.dumps(parsed_intent))
        idx += 1

    if status is not None:
        updates.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    if not updates:
        return

    sql = f"UPDATE agent_searches SET {', '.join(updates)} WHERE id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, *params)


async def complete_search(
    search_id: str | UUID,
    results_count: int,
    stale_count: int,
    duration_ms: Optional[int] = None,
) -> None:
    pool = await get_pool()
    sql = """
        UPDATE agent_searches
        SET status = 'complete',
            results_count = $2,
            stale_count = $3,
            duration_ms = $4,
            completed_at = NOW()
        WHERE id = $1
    """
    async with pool.acquire() as conn:
        await conn.execute(sql, UUID(str(search_id)), results_count, stale_count, duration_ms)


async def fail_search(search_id: str | UUID) -> None:
    pool = await get_pool()
    sql = "UPDATE agent_searches SET status = 'failed', completed_at = NOW() WHERE id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, UUID(str(search_id)))


async def save_result(search_id: str | UUID, job: Dict[str, Any]) -> str:
    pool = await get_pool()
    sql = """
        INSERT INTO agent_search_results
            (search_id, company, role, stack, location, posted_at, date_unknown, relevance_score, url, source)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
    """
    posted_at_dt = None
    if job.get("posted_at"):
        try:
            posted_at_dt = datetime.fromisoformat(job["posted_at"])
        except Exception:
            posted_at_dt = None

    async with pool.acquire() as conn:
        res_id = await conn.fetchval(
            sql,
            UUID(str(search_id)),
            job.get("company", ""),
            job.get("role", ""),
            job.get("stack") or [],
            job.get("location", ""),
            posted_at_dt,
            bool(job.get("date_unknown", False)),
            float(job.get("relevance_score", 0.0)),
            job.get("url", ""),
            job.get("source", "web_search"),
        )
    return str(res_id)


async def get_results(search_id: str | UUID) -> List[Dict[str, Any]]:
    pool = await get_pool()
    sql = """
        SELECT id, search_id, company, role, stack, location, posted_at, date_unknown, relevance_score, url, source, saved_to_pipeline, created_at
        FROM agent_search_results
        WHERE search_id = $1
        ORDER BY date_unknown ASC, posted_at DESC NULLS LAST
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, UUID(str(search_id)))

    results = []
    now = datetime.now(timezone.utc)
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["search_id"] = str(d["search_id"])
        if d.get("posted_at"):
            p_dt = d["posted_at"]
            if p_dt.tzinfo is None:
                p_dt = p_dt.replace(tzinfo=timezone.utc)
            d["posted_at"] = p_dt.isoformat()
            d["days_ago"] = max(0, (now - p_dt).days)
        else:
            d["posted_at"] = None
            d["days_ago"] = None
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        results.append(d)
    return results


async def get_result_by_id(result_id: str | UUID) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    sql = "SELECT * FROM agent_search_results WHERE id = $1"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, UUID(str(result_id)))
    if not row:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["search_id"] = str(d["search_id"])
    return d


async def mark_result_saved(result_id: str | UUID) -> None:
    pool = await get_pool()
    sql = "UPDATE agent_search_results SET saved_to_pipeline = true WHERE id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, UUID(str(result_id)))


async def get_recent_searches(limit: int = 20) -> List[Dict[str, Any]]:
    pool = await get_pool()
    sql = """
        SELECT id, query, filters, parsed_intent, results_count, stale_count, status, provider_used, created_at, completed_at
        FROM agent_searches
        ORDER BY created_at DESC
        LIMIT $1
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, limit)

        results = []
        for r in rows:
            d = dict(r)
            d["id"] = str(d["id"])
            if d.get("filters") and isinstance(d["filters"], str):
                d["filters"] = json.loads(d["filters"])
            if d.get("parsed_intent") and isinstance(d["parsed_intent"], str):
                d["parsed_intent"] = json.loads(d["parsed_intent"])
            d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
            d["completed_at"] = d["completed_at"].isoformat() if d.get("completed_at") else None
            results.append(d)
        return results
    except Exception as e:
        logger.error("Error in get_recent_searches: %s", e)
        return []
