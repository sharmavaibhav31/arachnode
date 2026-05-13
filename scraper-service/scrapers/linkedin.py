"""
scrapers/linkedin.py — LinkedIn public job search scraper using Playwright.

IMPORTANT: LinkedIn scraping is inherently fragile.  Their UI changes
frequently.  All selectors are documented below for easy maintenance.

Target URL:
    https://www.linkedin.com/jobs/search/?keywords={role}&location=India&f_TPR=r604800

Selector notes (last verified March 2026):
──────────────────────────────────────────────────────────────────────────────
  Job list container    ul.jobs-search__results-list
                        OR  div.base-search-card  (card-level fallback)
  Individual card       li  (direct children of the list)
  Title                 h3.base-search-card__title
  Company               h4.base-search-card__subtitle  a
                        OR  h4.base-search-card__subtitle
  Location              span.job-search-card__location
  Job URL               a.base-card__full-link[href]
                        (the <a> wrapping the entire card)
  Posted date           time[datetime]   ← HTML <time> element inside card

LinkedIn does NOT expose a stable skills/stack field on the public listing
page — stack is left empty and should be enriched by the aggregator based
on the role title + the user's requested stack filters.

Rate-limiting notes:
  - LinkedIn blocks bots that scroll too fast or send too many requests.
  - We wait at least 4 s between each scroll step.
  - We only load ONE page (infinite-scroll up to ~25 cards); requesting
    more pages requires session cookies which we intentionally avoid.
  - If you see a redirect to /authwall, the IP has been rate-limited.
    Back off for 30–60 minutes.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import PlatformScraper

logger = logging.getLogger(__name__)

MIN_SCROLL_DELAY = 4.0   # seconds — do NOT lower this

# ── Selectors ── loaded from YAML config
from selectors import SelectorLoader

_selector_loader = SelectorLoader()
_CARD_SEL      = _selector_loader.get("job_card")
_TITLE_SEL     = _selector_loader.get("title")
_COMPANY_SEL   = _selector_loader.get("company")
_LOCATION_SEL  = _selector_loader.get("location")
_LINK_SEL      = _selector_loader.get("job_url")
_TIME_SEL      = _selector_loader.get("posted_date")

def _build_url(role: str) -> str:
    kw = quote_plus(role)
    # f_TPR=r604800 → past week; geoId=102713980 → India
    return (
        f"https://www.linkedin.com/jobs/search/"
        f"?keywords={kw}&location=India&geoId=102713980"
        f"&f_TPR=r604800&position=1&pageNum=0"
    )


class LinkedInScraper(PlatformScraper):
    source_name = "linkedin"

    def __init__(self) -> None:
        self._delay: float = max(
            float(os.environ.get("SCRAPER_DELAY_SECONDS", 3)),
            MIN_SCROLL_DELAY,
        )

    async def scrape(self, role: str, stack: list[str]) -> list[dict[str, Any]]:
        url = _build_url(role)
        jobs: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                locale="en-IN",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            try:
                logger.info("[LinkedIn] Navigating to: %s", url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

                # Check for auth-wall redirect
                if "/authwall" in page.url or "/login" in page.url:
                    logger.warning(
                        "[LinkedIn] Redirected to auth page — likely rate-limited. "
                        "Returning empty result."
                    )
                    return []

                # Wait for at least one job card to appear
                try:
                    await page.wait_for_selector(_CARD_SEL, timeout=15_000)
                except PWTimeout:
                    logger.warning("[LinkedIn] No job cards found within timeout.")
                    return []

                # Scroll down twice to trigger lazy-load (≥4 s between scrolls)
                for _ in range(2):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(self._delay)

                cards = await page.query_selector_all(_CARD_SEL)
                logger.info("[LinkedIn] Found %d card elements", len(cards))

                for card in cards:
                    try:
                        title_el   = await card.query_selector(_TITLE_SEL)
                        company_el = await card.query_selector(_COMPANY_SEL)
                        loc_el     = await card.query_selector(_LOCATION_SEL)
                        link_el    = await card.query_selector(_LINK_SEL)
                        time_el    = await card.query_selector(_TIME_SEL)

                        title   = (await title_el.inner_text()).strip()   if title_el   else ""
                        company = (await company_el.inner_text()).strip() if company_el else ""
                        location= (await loc_el.inner_text()).strip()     if loc_el     else ""
                        job_url = await link_el.get_attribute("href")     if link_el    else ""
                        posted  = await time_el.get_attribute("datetime") if time_el    else None

                        if not title or not company:
                            continue

                        jobs.append(
                            {
                                "company":   company,
                                "role":      title,
                                "source":    "linkedin",
                                "url":       job_url or url,
                                "stack":     [],          # not available on listing page
                                "product":   None,
                                "location":  location,
                                "posted_at": posted,
                            }
                        )
                    except Exception as exc:
                        logger.debug("[LinkedIn] Error parsing card: %s", exc)
                        continue

            except Exception as exc:
                logger.exception("[LinkedIn] Unexpected error: %s", exc)
            finally:
                await browser.close()

        logger.info("[LinkedIn] Total scraped: %d jobs for role '%s'", len(jobs), role)
        return jobs
