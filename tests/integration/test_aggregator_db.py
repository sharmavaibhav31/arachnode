"""
Layer 2 — Integration tests: Aggregator service (real Postgres)

Uses testcontainers-python to spin up a real postgres:15-alpine container
for the test session, then exercises the full db.py request-to-database flow:
  schema init → insert → query with filters → update status → stats

Run with:
  cd tests
  pytest integration/test_aggregator_db.py -v

Requires: pip install pytest pytest-asyncio testcontainers asyncpg
"""

import json
import pytest
import asyncpg
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "aggregator-service"))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_url():
    """Start a real Postgres container for the entire test session."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers not installed — run: pip install testcontainers")

    with PostgresContainer("postgres:15-alpine") as pg:
        # testcontainers exposes a SQLAlchemy-style URL; asyncpg needs postgresql://
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield url


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the session (required by pytest-asyncio)."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def pg_pool(postgres_url):
    """Create a real asyncpg pool and initialise the schema once per session."""
    import db

    # Point the module at the container
    os.environ["DATABASE_URL"] = postgres_url
    pool = await asyncpg.create_pool(dsn=postgres_url, min_size=1, max_size=5)
    # Run the schema DDL directly (mirrors db._init_schema)
    async with pool.acquire() as conn:
        await conn.execute(db._SCHEMA_SQL)
    yield pool
    await pool.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert(pool, **overrides):
    """Insert a job with sensible defaults, return the record."""
    import db
    defaults = dict(
        company="Zepto",
        role="Backend Engineer",
        source="remotive",
        url=None,
        stack=["Go", "Postgres"],
        product="Quick commerce",
        location="Bengaluru",
        posted_at=None,
    )
    defaults.update(overrides)
    return await db.insert_job(pool, **defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestInsertJob:
    async def test_insert_returns_record(self, pg_pool):
        import db
        row = await _insert(pg_pool, url="https://zepto.com/jobs/1")
        assert row is not None
        assert row["company"] == "Zepto"
        assert row["role"] == "Backend Engineer"
        assert row["status"] == "new"   # default

    async def test_insert_stores_stack_array(self, pg_pool):
        import db
        row = await _insert(pg_pool, url="https://zepto.com/jobs/2", stack=["Rust", "gRPC"])
        assert row is not None
        assert "Rust" in row["stack"]

    async def test_duplicate_url_silently_ignored(self, pg_pool):
        import db
        url = "https://zepto.com/jobs/unique-dedup-url"
        row1 = await _insert(pg_pool, url=url)
        row2 = await _insert(pg_pool, url=url)   # same URL → ON CONFLICT DO NOTHING
        assert row1 is not None
        assert row2 is None   # second insert returns nothing

    async def test_stack_none_allowed(self, pg_pool):
        import db
        row = await _insert(pg_pool, url="https://zepto.com/jobs/no-stack", stack=None)
        assert row is not None
        assert row["stack"] is None


@pytest.mark.asyncio
class TestGetJobs:
    async def test_returns_list(self, pg_pool):
        import db
        rows = await db.get_jobs(pg_pool, limit=10)
        assert isinstance(rows, list)

    async def test_stack_filter(self, pg_pool):
        import db
        # Insert a job with a unique stack tag
        unique_tag = "ElixirUnique123"
        await _insert(pg_pool, url="https://test.com/elixir-job", stack=[unique_tag])
        rows = await db.get_jobs(pg_pool, stack=[unique_tag])
        assert len(rows) >= 1
        assert all(unique_tag in (r["stack"] or []) for r in rows)

    async def test_status_filter(self, pg_pool):
        import db
        rows = await db.get_jobs(pg_pool, status="new", limit=50)
        assert all(r["status"] == "new" for r in rows)

    async def test_role_filter_case_insensitive(self, pg_pool):
        import db
        await _insert(pg_pool, url="https://test.com/sre-job", role="Site Reliability Engineer")
        rows = await db.get_jobs(pg_pool, role="site reliability")
        assert any("Site Reliability" in r["role"] for r in rows)

    async def test_limit_respected(self, pg_pool):
        import db
        rows = await db.get_jobs(pg_pool, limit=2)
        assert len(rows) <= 2


@pytest.mark.asyncio
class TestUpdateJobStatus:
    async def test_status_transitions(self, pg_pool):
        import db
        row = await _insert(pg_pool, url="https://test.com/status-job")
        assert row is not None
        job_id = row["id"]

        updated = await db.update_job_status(pg_pool, job_id, "applied")
        assert updated["status"] == "applied"

        reverted = await db.update_job_status(pg_pool, job_id, "new")
        assert reverted["status"] == "new"


@pytest.mark.asyncio
class TestGetStats:
    async def test_returns_expected_shape(self, pg_pool):
        import db
        stats = await db.get_stats(pg_pool)
        assert "by_source" in stats
        assert "by_status" in stats
        assert isinstance(stats["by_source"], dict)
        assert isinstance(stats["by_status"], dict)

    async def test_new_status_counted(self, pg_pool):
        import db
        stats = await db.get_stats(pg_pool)
        # We've inserted many 'new' jobs in this session
        assert stats["by_status"].get("new", 0) > 0
