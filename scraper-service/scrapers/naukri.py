"""
scrapers/naukri.py — Naukri.com scraper using httpx + BeautifulSoup.

Target URL pattern:
    https://www.naukri.com/{role-slug}-jobs?pageNo={n}

Selector notes (update here if Naukri changes its markup):
─────────────────────────────────────────────────────────
  Job cards         article.jobTuple           or  div.srp-jobtuple-root
  Title             a.title                    or  a[title]
  Company           a.comp-name                or  span.comp-name
  Location          span.loc span a            or  li.location span
  Skills            ul.tags-gt li              or  ul.tags li
  Posted date       span.job-post-day           or  span[title*="Posted"]
  Job URL           a.title[href]
─────────────────────────────────────────────────────────
Naukri uses a React-rendered shell; most of the job list is still delivered
as server-side HTML within the initial page load, so plain httpx works for
the first few pages.  If the payload becomes JS-only, swap this class to use
httpx with the internal API endpoint:
    https://www.naukri.com/jobapi/v3/search?keyword={role}&pageNo={n}
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .base import PlatformScraper, matches_roles, matches_stack

logger = logging.getLogger(__name__)

MAX_PAGES = 3
BASE_URL = "https://www.naukri.com"

# ── Realistic browser headers to reduce 403s ─────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.naukri.com/",
}


def _role_to_slug(role: str) -> str:
    """'Backend Engineer' → 'backend-engineer'"""
    return re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")


def _parse_cards(soup: BeautifulSoup, roles: list[str], stack: list[str]) -> list[dict[str, Any]]:
    """
    Extract job dicts from one page of search results.

    SELECTOR MAP — update these strings when Naukri changes its HTML:
      card_sel   : top-level job card element
      title_sel  : anchor tag containing the job title
      company_sel: element containing company name
      loc_sel    : element containing location text
      skills_sel : list items containing skill tags
      date_sel   : element containing the "posted N days ago" text
    """
    card_sel    = "article.jobTuple, div.srp-jobtuple-root"
    title_sel   = "a.title, a.jobTitle"
    company_sel = "a.comp-name, span.comp-name"
    loc_sel     = "span.loc span a, li.location span, span.locWdth"
    skills_sel  = "ul.tags-gt li, ul.tags li"
    date_sel    = "span.job-post-day, span[title]"

    jobs: list[dict[str, Any]] = []

    for card in soup.select(card_sel):
        try:
            title_el = card.select_one(title_sel)
            if not title_el:
                continue

            title   = title_el.get_text(strip=True)
            job_url = title_el.get("href", "")
            if not job_url.startswith("http"):
                job_url = BASE_URL + job_url

            company_el = card.select_one(company_sel)
            company    = company_el.get_text(strip=True) if company_el else ""

            loc_el   = card.select_one(loc_sel)
            location = loc_el.get_text(strip=True) if loc_el else ""

            skills = [li.get_text(strip=True) for li in card.select(skills_sel)]

            date_el   = card.select_one(date_sel)
            posted_at = date_el.get_text(strip=True) if date_el else ""

            if not company:
                continue

            # Only keep jobs whose title matches one of our target roles
            if not matches_roles(title, roles):
                continue

            # Stack filter: only apply if job has listed skills
            if stack and skills and not matches_stack(skills, stack):
                continue

            jobs.append(
                {
                    "company":   company,
                    "role":      title,
                    "source":    "naukri",
                    "url":       job_url,
                    "stack":     skills,
                    "product":   None,
                    "location":  location,
                    "posted_at": posted_at or None,
                }
            )
        except Exception as exc:
            logger.debug("Error parsing Naukri card: %s", exc)
            continue

    return jobs


class NaukriScraper(PlatformScraper):
    source_name = "naukri"

    def __init__(self) -> None:
        self._delay: float = float(os.environ.get("SCRAPER_DELAY_SECONDS", 3))

    async def scrape(self, roles: list[str], stack: list[str]) -> list[dict[str, Any]]:
        primary_role = roles[0] if roles else "software engineer"
        slug = primary_role.lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
        all_jobs: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=20,
        ) as client:
            for page in range(1, MAX_PAGES + 1):
                url = f"{BASE_URL}/{slug}-jobs?pageNo={page}"
                logger.info("[Naukri] Fetching page %d: %s", page, url)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "[Naukri] HTTP %s on page %d — stopping pagination.",
                        exc.response.status_code, page,
                    )
                    break
                except httpx.RequestError as exc:
                    logger.error("[Naukri] Request error on page %d: %s", page, exc)
                    break

                soup  = BeautifulSoup(resp.text, "html.parser")
                cards = _parse_cards(soup, roles, stack)
                logger.info("[Naukri] Page %d → %d jobs", page, len(cards))
                all_jobs.extend(cards)

                if not cards:
                    # No results on this page — stop early
                    break

                if page < MAX_PAGES:
                    delay = self._delay + random.uniform(-0.5, 1.0)
                    await asyncio.sleep(max(delay, 1.5))

        logger.info("[Naukri] Total scraped: %d jobs for roles %s", len(all_jobs), roles)
        return all_jobs
