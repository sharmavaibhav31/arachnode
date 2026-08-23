"""
stream_emitter.py — SSE formatting helper and Redis Stream emitter.

Emits saved job postings onto the canonical 'jobs:raw' Redis Stream consumed by
the Job Aggregator Service, preserving repository standards.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

STREAM_NAME = "jobs:raw"
STREAM_MAXLEN = 50_000

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", 6379))
        _redis = aioredis.Redis(host=host, port=port, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def format_sse(event_type: str, data: Dict[str, Any]) -> str:
    """Format data dict as an SSE event string."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def emit_job(job: Dict[str, Any]) -> None:
    """
    Publish a single job-event dict to the Redis Stream 'jobs:raw'.
    Mandatory fields: company, role.
    """
    redis_client = await get_redis()

    event: Dict[str, str] = {
        "company": str(job.get("company", "")).strip(),
        "role": str(job.get("role", "")).strip(),
        "source": str(job.get("source", "")),
        "url": str(job.get("url", "")),
        "stack": json.dumps(job.get("stack") or []),
        "product": str(job.get("product", "") or ""),
        "location": str(job.get("location", "") or ""),
        "posted_at": str(job.get("posted_at", "") or ""),
    }

    if not event["company"] or not event["role"]:
        logger.debug("Skipping Redis emit — missing company or role: %s", job)
        return

    await redis_client.xadd(STREAM_NAME, event, maxlen=STREAM_MAXLEN, approximate=True)
    logger.info("Emitted to jobs:raw Redis stream: %s @ %s", event["role"], event["company"])
