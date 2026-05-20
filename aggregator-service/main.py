"""
main.py — FastAPI application for the Job Aggregator Service.

Endpoints
---------
GET  /jobs                   List jobs with optional filters
GET  /jobs/export?format=csv Export jobs as CSV with optional filters
GET  /jobs/{id}              Fetch a single job by UUID
PATCH /jobs/{id}/status      Update a job's status
GET  /stats                  Aggregate counts by source and status
GET  /health                 Liveness / readiness probe
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

import db as database
import consumer as stream_consumer
from models import JobOut, StatusUpdate, StatsOut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan: start DB pool + background consumer on startup; teardown on exit
# ---------------------------------------------------------------------------

_consumer_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    # Initialise PostgreSQL pool (also creates the schema if needed)
    await database.create_pool()

    # Launch the Redis Stream consumer as a background asyncio task
    _consumer_task = asyncio.create_task(
        stream_consumer.run_consumer(), name="redis-consumer"
    )
    logger.info("Background Redis consumer task started.")

    yield  # ← application is running

    # Graceful shutdown
    if _consumer_task and not _consumer_task.done():
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass

    await database.close_pool()
    logger.info("Aggregator service shut down cleanly.")


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Job Aggregator Service",
    description="Consumes job events from a Redis Stream and exposes a queryable REST API.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _record_to_dict(row) -> dict:
    """Convert an asyncpg Record to a plain dict, handling UUID / datetime."""
    return dict(row)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.get("/jobs", response_model=List[JobOut], tags=["jobs"])
async def list_jobs(
    role: Optional[str] = Query(None, description="Substring match on role title"),
    stack: Optional[str] = Query(
        None,
        description="Comma-separated tech tags; returns jobs whose stack contains ALL of them",
    ),
    status: Optional[str] = Query(None, description="Filter by status: new | applied | ignored"),
    sort: str = Query("latest", description="Sort order: latest | oldest"),
    limit: int = Query(50, ge=1, le=500, description="Max results to return"),
):
    if sort not in ("latest", "oldest"):
        raise HTTPException(status_code=400, detail="sort must be 'latest' or 'oldest'")
    if status and status not in ("new", "applied", "ignored"):
        raise HTTPException(status_code=400, detail="status must be new | applied | ignored")

    stack_list = [s.strip() for s in stack.split(",")] if stack else None

    pool = await database.get_pool()
    rows = await database.get_jobs(
        pool,
        role=role,
        stack=stack_list,
        status=status,
        sort=sort,
        limit=limit,
    )
    return [JobOut(**_record_to_dict(r)) for r in rows]


@app.get("/jobs/export", tags=["jobs"])
async def export_jobs_csv(
    role: Optional[str] = Query(None, description="Substring match on role title"),
    stack: Optional[str] = Query(
        None,
        description="Comma-separated tech tags; returns jobs whose stack contains ALL of them",
    ),
    status: Optional[str] = Query(None, description="Filter by status: new | applied | ignored"),
    sort: str = Query("latest", description="Sort order: latest | oldest"),
    format: str = Query("csv", description="Export format (only csv supported)"),
):
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only csv format is supported")
    if sort not in ("latest", "oldest"):
        raise HTTPException(status_code=400, detail="sort must be 'latest' or 'oldest'")
    if status and status not in ("new", "applied", "ignored"):
        raise HTTPException(status_code=400, detail="status must be new | applied | ignored")

    stack_list = [s.strip() for s in stack.split(",")] if stack else None

    pool = await database.get_pool()

    async def generate_csv():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        
        # Write header
        writer.writerow([
            "id", "company", "role", "source", "url", "stack", "product", 
            "location", "posted_at", "status", "created_at"
        ])
        yield buffer.getvalue()
        buffer.truncate(0)
        buffer.seek(0)
        
        # Stream data in chunks
        chunk_size = 1000
        chunk = []
        async for record in database.stream_jobs(
            pool,
            role=role,
            stack=stack_list,
            status=status,
            sort=sort,
        ):
            row = _record_to_dict(record)
            csv_row = [
                str(row["id"]),
                row["company"],
                row["role"],
                row["source"] or "",
                row["url"] or "",
                ",".join(row["stack"]) if row["stack"] else "",
                row["product"] or "",
                row["location"] or "",
                row["posted_at"].isoformat() if row["posted_at"] else "",
                row["status"],
                row["created_at"].isoformat(),
            ]
            chunk.append(csv_row)
            
            if len(chunk) >= chunk_size:
                writer.writerows(chunk)
                yield buffer.getvalue()
                buffer.truncate(0)
                buffer.seek(0)
                chunk = []
        
        # Yield remaining rows
        if chunk:
            writer.writerows(chunk)
            yield buffer.getvalue()

    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobs.csv"}
    )


@app.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"])
async def get_job(job_id: UUID):
    pool = await database.get_pool()
    row = await database.get_job_by_id(pool, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(**_record_to_dict(row))


@app.patch("/jobs/{job_id}/status", response_model=JobOut, tags=["jobs"])
async def patch_job_status(job_id: UUID, body: StatusUpdate):
    pool = await database.get_pool()
    row = await database.update_job_status(pool, job_id, body.status)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(**_record_to_dict(row))


@app.get("/stats", response_model=StatsOut, tags=["analytics"])
async def get_stats():
    pool = await database.get_pool()
    stats = await database.get_stats(pool)
    return StatsOut(**stats)
