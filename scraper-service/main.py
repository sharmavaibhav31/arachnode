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
import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

import emit as emitter
from scrapers.naukri import NaukriScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.internshala import IntershalaScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

PLATFORMS = ["naukri", "linkedin", "internshala"]


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


# ---------------------------------------------------------------------------
# CLI entry point for --verify flag
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Scraper Selector Verification")
    parser.add_argument(
        '--verify', 
        action='store_true', 
        help='Verify LinkedIn selectors from config file'
    )
    args = parser.parse_args()
    
    if args.verify:
        print("\n" + "="*50)
        print("LinkedIn Selector Verification")
        print("="*50 + "\n")
        
        try:
            from selectors import SelectorLoader
            loader = SelectorLoader()
            results = loader.verify()
            
            all_valid = True
            for name, info in results.items():
                status = "✅" if info["valid"] else "❌"
                print(f"{status} {name}: {info['selector']}")
                if not info["valid"]:
                    all_valid = False
            
            print("\n" + "="*50)
            if all_valid:
                print("✅ All selectors are valid!")
            else:
                print("❌ Some selectors are invalid or missing.")
                print("   Update config/linkedin_selectors.yaml with correct selectors.")
            print("="*50)
            
        except FileNotFoundError:
            print("❌ Config file not found: config/linkedin_selectors.yaml")
            print("   Please create the YAML config file first.")
        except Exception as e:
            print(f"❌ Error during verification: {e}")
        
        exit(0)
    
    # Normal FastAPI startup
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    