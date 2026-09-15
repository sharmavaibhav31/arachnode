"""
storage.py — PostgreSQL persistence helper for Gemini Agent sessions.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


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
    logger.info("Gemini Agent storage PostgreSQL pool ready.")
    return _pool


async def get_pool() -> Optional[asyncpg.Pool]:
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Gemini Agent storage PostgreSQL pool closed.")


_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS agent_sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   UUID NOT NULL UNIQUE,
  messages     JSONB NOT NULL DEFAULT '[]',
  context      JSONB,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);
"""


async def _init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    logger.info("Agent sessions schema verified/created.")


async def get_session(session_id: str | UUID) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if not pool:
        return None
    sid = UUID(str(session_id)) if isinstance(session_id, str) else session_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_sessions WHERE session_id = $1", sid)
        if not row:
            return None
        return {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "messages": json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"],
            "context": json.loads(row["context"]) if isinstance(row["context"], str) else row["context"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


async def save_session(session_id: str | UUID, messages: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    pool = await get_pool()
    sid = UUID(str(session_id)) if isinstance(session_id, str) else session_id
    messages_json = json.dumps(messages)
    context_json = json.dumps(context or {})

    if not pool:
        return {
            "session_id": str(sid),
            "messages": messages,
            "context": context or {},
        }

    sql = """
        INSERT INTO agent_sessions (session_id, messages, context, updated_at)
        VALUES ($1, $2::jsonb, $3::jsonb, NOW())
        ON CONFLICT (session_id) DO UPDATE
        SET messages = EXCLUDED.messages,
            context = EXCLUDED.context,
            updated_at = NOW()
        RETURNING *
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, sid, messages_json, context_json)
        return {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "messages": json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"],
            "context": json.loads(row["context"]) if isinstance(row["context"], str) else row["context"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }
