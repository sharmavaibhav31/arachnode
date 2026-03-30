"""
Layer 2 — Integration tests: Redis Stream consumer (real Redis)

Uses testcontainers-python to spin up a real redis:7-alpine container,
then exercises the consumer's message-processing flow end-to-end:
  publish event to stream  →  _process_message()  →  verify Postgres row

This test requires both a Redis container AND the Postgres pool from
test_aggregator_db.py.  Run the full integration suite together:

  pytest tests/integration/ -v

Requires: pip install pytest pytest-asyncio testcontainers asyncpg redis
"""

import asyncio
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def redis_url():
    """Start a real Redis container for the test session."""
    try:
        from testcontainers.redis import RedisContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    with RedisContainer("redis:7-alpine") as rc:
        yield f"redis://{rc.get_container_host_ip()}:{rc.get_exposed_port(6379)}"


@pytest.fixture(scope="session")
def postgres_url():
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed")

    with PostgresContainer("postgres:15-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield url


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def pg_pool(postgres_url):
    import asyncpg
    import db
    os.environ["DATABASE_URL"] = postgres_url
    pool = await asyncpg.create_pool(dsn=postgres_url, min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(db._SCHEMA_SQL)
    yield pool
    await pool.close()


@pytest.fixture(scope="session")
async def redis_client(redis_url):
    import redis.asyncio as aioredis
    client = aioredis.from_url(redis_url, decode_responses=False)
    yield client
    await client.aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> dict:
    """Build a synthetic Redis Stream message field dict."""
    base = {
        b"company": b"TestCorp",
        b"role": b"Backend Engineer",
        b"source": b"test",
        b"url": b"https://testcorp.com/job/" + str(uuid.uuid4()).encode(),
        b"stack": json.dumps(["Python", "FastAPI"]).encode(),
        b"product": b"Developer Tooling",
        b"location": b"Remote",
        b"posted_at": b"2024-03-01",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProcessMessage:
    async def test_valid_event_inserts_job(self, redis_client, pg_pool):
        import db
        from consumer import _process_message, STREAM_NAME, GROUP_NAME

        # Publish to the stream
        fields = _make_event(b"company": b"StreamCorp", b"url": b"https://streamcorp.com/job/1")
        msg_id = await redis_client.xadd(STREAM_NAME, fields)

        # Process it directly
        await _process_message(redis_client, pg_pool, msg_id, fields)

        # Verify it landed in Postgres
        rows = await db.get_jobs(pg_pool, role="Backend Engineer", limit=100)
        companies = [r["company"] for r in rows]
        assert "StreamCorp" in companies

    async def test_missing_company_skipped(self, redis_client, pg_pool):
        import db
        from consumer import _process_message, STREAM_NAME

        fields = _make_event()
        del fields[b"company"]
        msg_id = await redis_client.xadd(STREAM_NAME, fields)

        count_before = len(await db.get_jobs(pg_pool, limit=1000))
        await _process_message(redis_client, pg_pool, msg_id, fields)
        count_after = len(await db.get_jobs(pg_pool, limit=1000))

        assert count_after == count_before   # no new row

    async def test_invalid_stack_json_tolerated(self, redis_client, pg_pool):
        """Malformed stack JSON should not crash the consumer — row is inserted with stack=None."""
        import db
        from consumer import _process_message, STREAM_NAME

        unique_url = f"https://badstack.com/job/{uuid.uuid4()}"
        fields = _make_event(
            b"company": b"BadStackCo",
            b"url": unique_url.encode(),
            b"stack": b"not-valid-json",
        )
        msg_id = await redis_client.xadd(STREAM_NAME, fields)
        # Should not raise
        await _process_message(redis_client, pg_pool, msg_id, fields)

        rows = await db.get_jobs(pg_pool, role="Backend Engineer", limit=200)
        inserted = [r for r in rows if r["company"] == "BadStackCo"]
        assert len(inserted) >= 1
        assert inserted[0]["stack"] is None

    async def test_dedup_prevents_second_insert(self, redis_client, pg_pool):
        import db
        from consumer import _process_message, _dedup_key, STREAM_NAME

        # Clear any previous dedup key for this company+role pair
        key = _dedup_key("DedupCorp", "Backend Engineer")
        await redis_client.delete(key)

        shared_url = f"https://dedupcorp.com/job/{uuid.uuid4()}"
        fields = _make_event(b"company": b"DedupCorp", b"url": shared_url.encode())

        msg_id1 = await redis_client.xadd(STREAM_NAME, fields)
        msg_id2 = await redis_client.xadd(STREAM_NAME, fields)

        await _process_message(redis_client, pg_pool, msg_id1, fields)  # inserted
        await _process_message(redis_client, pg_pool, msg_id2, fields)  # deduped

        rows = await db.get_jobs(pg_pool, limit=500)
        matches = [r for r in rows if r["company"] == "DedupCorp"]
        assert len(matches) == 1   # exactly one row despite two messages
