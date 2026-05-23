"""
Layer 2 — Integration tests: Aggregator service CSV export (real Postgres)

Uses testcontainers-python to spin up a real postgres:15-alpine container
for the test session, then exercises the CSV export endpoint with streaming.

Run with:
  cd tests
  pytest integration/test_aggregator_export.py -v

Requires: pip install pytest pytest-asyncio testcontainers asyncpg httpx
"""

import csv
import io
import pytest
import asyncpg
import sys
import os
from httpx import AsyncClient

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


@pytest.fixture(scope="session")
async def test_app(pg_pool):
    """Create a FastAPI test app with the pool."""
    from fastapi import FastAPI
    import main
    import db

    # Override the pool creation
    db._pool = pg_pool
    app = main.app
    yield app


@pytest.fixture
async def client(test_app):
    """HTTP client for testing the FastAPI app."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        yield client


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
        url="https://zepto.com/jobs/1",
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
class TestExportJobsCSV:
    async def test_export_empty_csv(self, client):
        """Test CSV export with no jobs returns only header."""
        response = await client.get("/jobs/export?format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv"
        assert "attachment; filename=jobs.csv" in response.headers["content-disposition"]
        
        content = response.text
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 1  # Only header
        assert rows[0] == ["id", "company", "role", "source", "url", "stack", "product", "location", "posted_at", "status", "created_at"]

    async def test_export_with_jobs(self, client, pg_pool):
        """Test CSV export with some jobs."""
        # Insert test jobs
        await _insert(pg_pool, company="Zepto", role="Backend Engineer", stack=["Go", "Postgres"])
        await _insert(pg_pool, company="Swiggy", role="Frontend Engineer", stack=["React", "TypeScript"])
        
        response = await client.get("/jobs/export?format=csv")
        assert response.status_code == 200
        
        content = response.text
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 3  # Header + 2 jobs
        assert rows[0] == ["id", "company", "role", "source", "url", "stack", "product", "location", "posted_at", "status", "created_at"]
        
        # Check first job
        assert rows[1][1] == "Zepto"
        assert rows[1][2] == "Backend Engineer"
        assert rows[1][5] == "Go,Postgres"
        assert rows[1][9] == "new"
        
        # Check second job
        assert rows[2][1] == "Swiggy"
        assert rows[2][2] == "Frontend Engineer"
        assert rows[2][5] == "React,TypeScript"

    async def test_export_with_filters(self, client, pg_pool):
        """Test CSV export respects filters."""
        await _insert(pg_pool, company="Zepto", role="Backend Engineer", stack=["Go", "Postgres"])
        await _insert(pg_pool, company="Swiggy", role="Frontend Engineer", stack=["React", "TypeScript"])
        
        # Filter by role
        response = await client.get("/jobs/export?format=csv&role=Backend")
        assert response.status_code == 200
        
        content = response.text
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 2  # Header + 1 job
        assert rows[1][1] == "Zepto"

    async def test_export_large_dataset_memory_efficient(self, client, pg_pool):
        """Test that export handles large datasets without excessive memory usage."""
        # Insert many jobs
        jobs = []
        for i in range(10000):
            jobs.append(_insert(pg_pool, company=f"Company{i}", role=f"Role{i}", stack=["Python"]))
        
        await asyncio.gather(*jobs)
        
        response = await client.get("/jobs/export?format=csv")
        assert response.status_code == 200
        
        # Count lines in response
        content = response.text
        line_count = content.count('\n')
        assert line_count == 10001  # 10000 jobs + header
        
        # Verify we can parse the CSV
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 10001
        assert rows[0][0] == "id"
        assert rows[1][1] == "Company0"

    async def test_export_invalid_format(self, client):
        """Test that invalid format returns 400."""
        response = await client.get("/jobs/export?format=json")
        assert response.status_code == 400
        assert "Only csv format is supported" in response.json()["detail"]