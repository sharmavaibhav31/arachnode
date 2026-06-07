"""
consumer.py — Redis Stream consumer loop for the Job Aggregator Service.

Reads from the 'jobs:raw' stream using a consumer group so that messages
are not lost across restarts.  For each event it:
  1. Parses and normalises the job fields.
  2. Checks the Redis dedup key (MD5 of normalised company+role).
  3. If not a duplicate, inserts the job into PostgreSQL.
  4. ACKs the message so it is not redelivered.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from utils.date_utils import normalize_date

import redis.asyncio as aioredis

import db as database

logger = logging.getLogger(__name__)

# Stream / group constants
STREAM_NAME = "jobs:raw"
GROUP_NAME = "aggregator-group"
CONSUMER_NAME = "aggregator-1"
BLOCK_MS = 5_000          # block at most 5 s waiting for new messages
BATCH_SIZE = 10
DEDUP_TTL_SECONDS = 7 * 24 * 3600  # 7 days


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Lower-case, strip whitespace for dedup hashing."""
    return text.lower().strip()


def _dedup_key(company: str, role: str) -> str:
    raw = _normalise(company) + "|" + _normalise(role)
    md5 = hashlib.md5(raw.encode()).hexdigest()
    return f"dedup:agg:{md5}"


# ---------------------------------------------------------------------------
# Consumer lifecycle
# ---------------------------------------------------------------------------


async def _ensure_consumer_group(redis: aioredis.Redis) -> None:
    """Create the consumer group if it does not exist yet."""
    try:
        await redis.xgroup_create(
            STREAM_NAME, GROUP_NAME, id="0", mkstream=True
        )
        logger.info("Consumer group '%s' created on stream '%s'.", GROUP_NAME, STREAM_NAME)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            logger.info("Consumer group '%s' already exists.", GROUP_NAME)
        else:
            raise


async def _process_message(
    redis: aioredis.Redis,
    pool: Any,
    message_id: bytes,
    fields: Dict[bytes, bytes],
) -> None:
    """Parse one stream message and (conditionally) insert into Postgres."""
    # Decode bytes → str
    data: Dict[str, str] = {
        k.decode(): v.decode() for k, v in fields.items()
    }

    company = data.get("company", "").strip()
    role = data.get("role", "").strip()

    if not company or not role:
        logger.warning("Skipping message %s — missing company/role", message_id)
        await redis.xack(STREAM_NAME, GROUP_NAME, message_id)
        return

    # Deduplication
    key = _dedup_key(company, role)
    is_dup = await redis.exists(key)
    if is_dup:
        logger.debug("Duplicate skipped: %s | %s", company, role)
        await redis.xack(STREAM_NAME, GROUP_NAME, message_id)
        return

    # Deserialise stack JSON array
    stack_raw = data.get("stack", "[]")
    try:
        stack: Optional[list] = json.loads(stack_raw)
        if not isinstance(stack, list):
            stack = None
    except (json.JSONDecodeError, TypeError):
        stack = None

    posted_at = normalize_date(data.get("posted_at"))

    row = await database.insert_job(
        pool,
        company=company,
        role=role,
        source=data.get("source") or None,
        url=data.get("url") or None,
        stack=stack,
        product=data.get("product") or None,
        location=data.get("location") or None,
        posted_at=posted_at,
    )

    if row is not None:
        # Mark seen in Redis for dedup TTL
        await redis.set(key, "1", ex=DEDUP_TTL_SECONDS)
        logger.info("Inserted job: %s @ %s (id=%s)", role, company, row["id"])
    else:
        logger.debug("INSERT returned no row (URL conflict?): %s @ %s", role, company)

    await redis.xack(STREAM_NAME, GROUP_NAME, message_id)


async def _claim_pending(redis: aioredis.Redis, pool: Any) -> None:
    """
    On startup re-process any messages that were delivered but never ACK-ed
    (e.g. from a previous crash).  Uses XAUTOCLAIM with a 60-second min-idle.
    """
    start_id = "0-0"
    while True:
        result = await redis.xautoclaim(
            STREAM_NAME, GROUP_NAME, CONSUMER_NAME,
            min_idle_time=60_000,   # messages idle > 60 s
            start_id=start_id,
            count=BATCH_SIZE,
        )
        # result format: [next_start_id, [[id, fields], ...], deleted_ids]
        next_id, messages, _ = result
        if not messages:
            break
        for message_id, fields in messages:
            await _process_message(redis, pool, message_id, fields)
        if next_id == b"0-0":
            break
        start_id = next_id


# ---------------------------------------------------------------------------
# Main consumer loop
# ---------------------------------------------------------------------------


async def run_consumer() -> None:
    """
    Long-running coroutine consumed by FastAPI's lifespan as a background task.
    Connects to Redis, ensures the consumer group exists, then reads in a loop.
    """
    redis_host = os.environ.get("REDIS_HOST", "localhost")
    redis_port = int(os.environ.get("REDIS_PORT", 6379))

    redis = aioredis.Redis(
        host=redis_host,
        port=redis_port,
        decode_responses=False,  # we decode manually to handle mixed bytes
    )

    pool = await database.get_pool()
    await _ensure_consumer_group(redis)
    await _claim_pending(redis, pool)

    logger.info("Redis Stream consumer started — listening on '%s'.", STREAM_NAME)

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )

            if not results:
                # No new messages within BLOCK_MS; loop again.
                continue

            for _stream, messages in results:
                for message_id, fields in messages:
                    try:
                        await _process_message(redis, pool, message_id, fields)
                    except Exception as exc:
                        logger.exception(
                            "Error processing message %s: %s", message_id, exc
                        )

        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled — shutting down.")
            await redis.aclose()
            break
        except Exception as exc:
            logger.exception("Unexpected error in consumer loop: %s", exc)
            await asyncio.sleep(2)   # back-off before retrying
