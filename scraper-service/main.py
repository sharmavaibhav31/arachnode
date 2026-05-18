"""
main.py — FastAPI entrypoint for the Platform Scraper Service.

Endpoints
─────────
  POST /scrape    Trigger all scrapers concurrently
  GET  /health    Liveness probe
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

import emit as emitter
from discovery.dork_builder import DEFAULT_PLATFORMS, JobDorkConfig
from discovery.dork_discovery import DorkDiscoveryService, provider_from_env
from scrapers.naukri import NaukriScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.internshala import IntershalaScraper
from scrapers.google_dork import GoogleDorkScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PLATFORMS = ["naukri", "linkedin", "internshala", "google_dork"]


# ---------------------------------------------------------------------------
# Lifespan — warm up Redis connection on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly open the Redis connection so the first /scrape is fast
    await emitter.get_redis()
    logger.info("Scraper service ready.")
    yield
    await emitter.close_redis()
    logger.info("Scraper service shut down.")


app = FastAPI(
    title="Platform Scraper Service",
    description=(
        "Scrapes Naukri, LinkedIn (public), and Internshala for job listings "
        "and emits events to the jobs:raw Redis Stream."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    role: str = "Backend Engineer"
    stack: list[str] = []


class ScrapeResponse(BaseModel):
    triggered: bool
    platforms: list[str]


class DorkDiscoverRequest(BaseModel):
    role: str = "Backend Engineer"
    stack: list[str] = []
    location: str | None = None
    year: int | None = None
    after: date | None = None
    platforms: list[str] = []
    max_queries: int = 8
    results_per_query: int = 10


class DorkDiscoverResponse(BaseModel):
    queries: list[str]
    candidates: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Background scrape runner
# ---------------------------------------------------------------------------

async def _run_all_scrapers(role: str, stack: list[str]) -> None:
    """
    Run all three scrapers concurrently then emit results to Redis.
    Designed to be launched as a BackgroundTask so /scrape returns immediately.
    """
    scrapers = [
        NaukriScraper(),
        LinkedInScraper(),
        IntershalaScraper(),
        GoogleDorkScraper(),
    ]

    # Run all scrapers in parallel; capture per-scraper exceptions.
    results = await asyncio.gather(
        *[s.scrape(role, stack) for s in scrapers],
        return_exceptions=True,
    )

    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error(
                "[%s] Scraper raised an exception: %s",
                scraper.source_name, result,
            )
            continue

        logger.info(
            "[%s] Emitting %d jobs.", scraper.source_name, len(result)
        )
        emitted = await emitter.emit_jobs(result)
        logger.info("[%s] Emitted %d / %d jobs.", scraper.source_name, emitted, len(result))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse, tags=["scraping"])
async def trigger_scrape(body: ScrapeRequest, background_tasks: BackgroundTasks):
    """
    Trigger all platform scrapers concurrently in the background.
    Returns immediately while scraping happens asynchronously.
    """
    background_tasks.add_task(_run_all_scrapers, body.role, body.stack)
    return ScrapeResponse(triggered=True, platforms=PLATFORMS)


@app.post("/discover/dorks", response_model=DorkDiscoverResponse, tags=["discovery"])
async def discover_dorks(body: DorkDiscoverRequest):
    """
    Generate dork queries and, when a provider is configured, return filtered
    discovery candidates. This endpoint is demo-friendly and does not emit jobs.
    """
    config = JobDorkConfig(
        role=body.role,
        stack=tuple(body.stack),
        location=body.location,
        year=body.year,
        after=body.after,
        platforms=tuple(body.platforms) or DEFAULT_PLATFORMS,
        max_queries=body.max_queries,
    )
    response = await DorkDiscoveryService(provider=provider_from_env()).discover(
        config,
        results_per_query=body.results_per_query,
    )
    return DorkDiscoverResponse(
        queries=response.queries,
        candidates=[
            {
                "title": candidate.title,
                "url": candidate.url,
                "snippet": candidate.snippet,
                "query": candidate.query,
                "score": candidate.score,
            }
            for candidate in response.candidates
        ],
    )
