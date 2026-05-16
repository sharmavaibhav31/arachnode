"""
Google dork discovery adapter for the platform scraper service.

This scraper keeps external search APIs optional. Without SERPER_API_KEY,
GOOGLE_CSE_API_KEY/GOOGLE_CSE_ID, or DORK_SEED_RESULTS it only logs generated
queries and emits no jobs.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from urllib.parse import urlsplit

from discovery.dork_builder import DEFAULT_PLATFORMS, JobDorkConfig
from discovery.dork_discovery import DorkDiscoveryService, provider_from_env
from scrapers.base import PlatformScraper

logger = logging.getLogger(__name__)


def _company_from_url(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] in {"careers", "jobs"}:
        return parts[1].replace("-", " ").title()
    if len(parts) >= 2:
        return parts[-2].replace("-", " ").title()
    return host or "Unknown Company"


def _parse_after(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        logger.warning("Ignoring invalid DORK_AFTER date: %s", value)
        return None


class GoogleDorkScraper(PlatformScraper):
    source_name = "google_dork"

    async def scrape(self, role: str, stack: list[str]) -> list[dict]:
        platforms = tuple(
            item.strip()
            for item in os.environ.get("DORK_PLATFORMS", "").split(",")
            if item.strip()
        )
        config = JobDorkConfig(
            role=role,
            stack=tuple(stack),
            location=os.environ.get("DORK_LOCATION"),
            year=int(os.environ["DORK_YEAR"]) if os.environ.get("DORK_YEAR") else None,
            after=_parse_after(os.environ.get("DORK_AFTER")),
            platforms=platforms or DEFAULT_PLATFORMS,
            max_queries=int(os.environ.get("DORK_MAX_QUERIES", "8")),
        )

        service = DorkDiscoveryService(provider=provider_from_env())
        response = await service.discover(
            config,
            results_per_query=int(os.environ.get("DORK_RESULTS_PER_QUERY", "10")),
        )

        logger.info("[GoogleDork] Generated %d queries", len(response.queries))
        for query in response.queries:
            logger.info("[GoogleDork] query: %s", query)

        jobs: list[dict] = []
        for candidate in response.candidates:
            jobs.append(
                {
                    "company": _company_from_url(candidate.url),
                    "role": candidate.title or role,
                    "source": self.source_name,
                    "url": candidate.url,
                    "stack": stack,
                    "product": None,
                    "location": config.location,
                    "posted_at": None,
                }
            )

        logger.info("[GoogleDork] Accepted %d discovered URLs", len(jobs))
        return jobs
