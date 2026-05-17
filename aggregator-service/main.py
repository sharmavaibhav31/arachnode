"""
main.py — FastAPI application for the Job Aggregator Service.

Endpoints
---------
GET  /jobs                   List jobs with optional filters
GET  /jobs/{id}              Fetch a single job by UUID
PATCH /jobs/{id}/status      Update a job's status
GET  /stats                  Aggregate counts by source and status
GET  /health                 Liveness / readiness probe
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from enum import Enum
from typing import List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

import db as database
import consumer as stream_consumer
from models import JobOut, StatusUpdate, StatsOut

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
# Use a standardized JSON-friendly format for better observability in production.
# Consider using a structured logging library like `structlog` for complex apps.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Enums
# ---------------------------------------------------------------------------
class JobStatus(str, Enum):
    NEW = "new"
    APPLIED = "applied"
    IGNORED = "ignored"

class SortOrder(str, Enum):
    LATEST = "latest"
    OLDEST = "oldest"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_consumer_task: Optional[asyncio.Task] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task

    logger.info("Initializing database pool...")
    try:
        await database.create_pool()
    except Exception as e:
        logger.critical(f"Failed to initialize database pool: {e}", exc_info=True)
        # We raise here because the app cannot function without the DB.
        raise

    logger.info("Starting background Redis consumer task...")
    _consumer_task = asyncio.create_task(
        stream_consumer.run_consumer(), name="redis-consumer"
    )

    yield  # Application is running

    logger.info("Initiating graceful shutdown...")
    
    # 1. Shutdown the consumer task cleanly
    if _consumer_task and not _consumer_task.done():
        logger.info("Cancelling background consumer task...")
        _consumer_task.cancel()
        try:
            # Wait for the task to finish cancellation process with a timeout
            # to prevent hanging the shutdown process indefinitely.
            await asyncio.wait_for(_consumer_task, timeout=5.0)
        except asyncio.CancelledError:
            logger.info("Consumer task cancelled successfully.")
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for consumer task to cancel.")
        except Exception as e:
             logger.error(f"Unexpected error during consumer shutdown: {e}", exc_info=True)

    # 2. Close the database pool
    logger.info("Closing database pool...")
    try:
        await database.close_pool()
    except Exception as e:
        logger.error(f"Error closing database pool: {e}", exc_info=True)

    logger.info("Aggregator service shut down cleanly.")

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Job Aggregator Service",
    description="Consumes job events from a Redis Stream and exposes a queryable REST API.",
    version="1.0.0",
    lifespan=lifespan,
    # Adding default response definitions for common errors improves Swagger UI
    responses={
        400: {"description": "Bad Request"},
        404: {"description": "Not Found"},
        500: {"description": "Internal Server Error"},
    }
)

# ---------------------------------------------------------------------------
# Exception Handlers
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions. Prevents leaking stack traces to clients
    while ensuring the error is logged centrally.
    """
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error. Please try again later."},
    )

# Optional: Customize validation error response format if needed
# @app.exception_handler(RequestValidationError)
# async def validation_exception_handler(request: Request, exc: RequestValidationError):
#     ...

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _record_to_dict(row) -> dict:
    """Convert an asyncpg Record to a plain dict."""
    return dict(row)

def _parse_stack_query(stack: Optional[str]) -> Optional[List[str]]:
    """Safely parse and validate the stack query parameter."""
    if not stack:
        return None
    
    # Split, strip whitespace, and remove empty strings caused by trailing/double commas
    parsed = [s.strip() for s in stack.split(",") if s.strip()]
    
    if not parsed:
        return None # E.g., if input was just commas " , , "
    
    return parsed

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    """
    Liveness and Readiness probe.
    Enhancement: Verifies database connectivity to ensure the service is truly ready.
    """
    try:
        pool = await database.get_pool()
        # Execute a lightweight query to verify the connection is alive
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
         logger.error(f"Healthcheck failed: {e}")
         # Return 503 Service Unavailable if the DB is down
         return JSONResponse(
             status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
             content={"status": "error", "database": "disconnected"}
         )


@app.get(
    "/jobs", 
    response_model=List[JobOut], 
    tags=["jobs"],
    summary="List and filter jobs",
    description="Retrieve a list of jobs based on optional filters like role, tech stack, and status."
)
async def list_jobs(
    role: Optional[str] = Query(None, description="Substring match on role title"),
    stack: Optional[str] = Query(
        None,
        description="Comma-separated tech tags (e.g., 'python,fastapi'). Returns jobs whose stack contains ALL of them.",
    ),
    # Use the Enums for validation and automatic Swagger UI documentation
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
    sort: SortOrder = Query(SortOrder.LATEST, description="Sort order"),
    limit: int = Query(50, ge=1, le=500, description="Max results to return"),
):
    
    stack_list = _parse_stack_query(stack)

    # Use standard FastAPI dependency injection pattern for DB pool (Ideal)
    # However, to avoid rewriting the `db.py` interface, we fetch it here.
    try:
        pool = await database.get_pool()
        rows = await database.get_jobs(
            pool,
            role=role,
            stack=stack_list,
            status=status.value if status else None, # Extract string value from Enum
            sort=sort.value,
            limit=limit,
        )
        return [JobOut(**_record_to_dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"Error fetching jobs: {e}", exc_info=True)
        # Raising HTTPException here lets FastAPI handle the response generation consistently
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database query failed")


@app.get(
    "/jobs/{job_id}", 
    response_model=JobOut, 
    tags=["jobs"],
    summary="Get a specific job"
)
async def get_job(job_id: UUID):
    try:
        pool = await database.get_pool()
        row = await database.get_job_by_id(pool, job_id)
    except Exception as e:
        logger.error(f"Error fetching job {job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database query failed")

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    
    return JobOut(**_record_to_dict(row))


@app.patch(
    "/jobs/{job_id}/status", 
    response_model=JobOut, 
    tags=["jobs"],
    summary="Update job status"
)
async def patch_job_status(job_id: UUID, body: StatusUpdate):
    try:
        pool = await database.get_pool()
        # Assumes StatusUpdate model handles validation of allowed statuses
        row = await database.update_job_status(pool, job_id, body.status)
    except Exception as e:
        logger.error(f"Error updating job {job_id} status: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database update failed")

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    
    return JobOut(**_record_to_dict(row))


@app.get(
    "/stats", 
    response_model=StatsOut, 
    tags=["analytics"],
    summary="Get job statistics"
)
async def get_stats():
    try:
        pool = await database.get_pool()
        stats = await database.get_stats(pool)
        # Consider edge case: db.get_stats returns None or empty dict if no data
        if not stats:
            return StatsOut() # Return default empty stats if DB query returns empty
        return StatsOut(**stats)
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database query failed")
