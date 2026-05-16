"""
scrapers/unstop.py — Unstop (formerly Dare2Compete) scraper using Playwright.

Unstop is an Angular SPA with server-side-rendered listing pages.
Listing pages use NUMBERED pagination (?page=N) — NOT infinite scroll.

Target URLs
───────────
  https://unstop.com/jobs?page={n}
  https://unstop.com/internships?page={n}

URL pattern per listing
───────────────────────
  /jobs/{role-slug}-{company-slug}-{id}
  /internships/{role-slug}-{company-slug}-{id}

Card text pattern (from DOM inner_text, last verified May 2026)
───────────────────────────────────────────────────────────────
  {role} {company} {experience} {job_type} {work_mode} [| {location}]
  {role} {tags...} [{salary}] Prize Icon Posted {date} {N} days left

  The role title appears TWICE — once before the experience marker, and again
  at the start of the tags block. We use this repetition to reliably split the
  pre-experience text into role + company with no CSS class dependency.

Primary CSS selector (last verified May 2026)
─────────────────────────────────────────────
  a[href*="/jobs/"], a[href*="/internships/"]
  (each listing card is a single clickable <a> element)

Pagination
──────────
  Unstop shows numbered pages (1-6+). We scrape MAX_PAGES per section.
  Two sections (jobs + internships) × MAX_PAGES pages each.

Rate-limiting notes
───────────────────
  Keep SCRAPER_DELAY_SECONDS >= 3 between page loads.
  Do not run more than 1 concurrent Playwright context against Unstop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from .base import PlatformScraper

logger = logging.getLogger(__name__)

BASE_URL  = "https://unstop.com"
MAX_PAGES = 3       # pages per section (jobs + internships = 6 total page loads)

# Sections to scrape — order matters for log readability
_SECTIONS = ["jobs", "internships"]

# ── Primary selector ─────────────────────────────────────────────────────────
# Every listing card on Unstop is wrapped in a single <a> linking to the
# opportunity. This one selector captures both jobs and internship cards.
_CARD_SEL = 'a[href*="/jobs/"], a[href*="/internships/"]'

# ── Text parsing regexes ─────────────────────────────────────────────────────

# Anchor 1: experience requirement — always present, used to split the text
_EXP_PAT = re.compile(
    r"\b(No prior experience required|\d+\s*[-–]\s*\d+\s*years?)\b",
    re.IGNORECASE,
)

# Anchor 2: work mode — appears right after job type, before optional location
_WORK_MODE_PAT = re.compile(
    r"\b(Work from Home|In Office|On Field|Hybrid|Remote)\b",
    re.IGNORECASE,
)

# Location: "| City" or "| City, City2" — present only for non-WFH roles
_LOCATION_PAT = re.compile(r"\|\s*([^|\n]+?)(?=\s{2,}|\s[A-Z][a-z]|$)")

# Job type: Full Time / Part Time
_JOB_TYPE_PAT = re.compile(
    r"\b(Full[\s\u00A0]?Time|Part[\s\u00A0]?Time|Contract)\b",
    re.IGNORECASE,
)

# Salary / stipend  e.g. "8 K - 12 K/Month", "2.4 LPA", "40 K - 70 K/Month"
_SALARY_PAT = re.compile(
    r"([\d,]+\.?\d*\s*[KkLl]"               # leading amount + unit
    r"(?:\s*[-–]\s*[\d,]+\.?\d*\s*[KkLl])?" # optional range
    r"\s*(?:/\s*(?:Month|Annum|Year|month)|LPA|PA|lpa|pa))",
    re.IGNORECASE,
)

# Posted date e.g. "Posted May 16, 2026"
_POSTED_PAT = re.compile(r"Posted\s+(\w+\s+\d{1,2},?\s*\d{4})", re.IGNORECASE)


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_card(href: str, text: str) -> dict[str, Any] | None:
    """
    Parse a single Unstop card from its href and combined inner_text.

    Returns a dict matching the aggregator JobPosting schema, or None if
    the card cannot be reliably parsed (e.g. banner/quiz/featured cards).

    Role + company extraction strategy
    ────────────────────────────────────
    Unstop card text always follows:
        {role} {company}  <EXP_ANCHOR>  {job_type} {mode} [| {location}]
        {role}            ← role title repeated here at start of tags block

    We split the pre-experience text into role + company by finding the
    longest prefix of "pre_exp" that also appears at the start of the
    tags block (text_after_location). This requires no CSS class names.
    """
    # Normalise all whitespace to single spaces
    text = " ".join(text.split())
    if not text or len(text) < 20:
        return None

    # ── 1. Split on experience marker ────────────────────────────────────────
    exp_match = _EXP_PAT.search(text)
    if not exp_match:
        # Cards without an experience marker are banners / quiz promos — skip
        return None

    pre_exp  = text[: exp_match.start()].strip()   # "Role Company"
    post_exp = text[exp_match.end() :].strip()      # "Full Time Work from Home | City Role tags..."

    # ── 2. Work mode and location ─────────────────────────────────────────────
    mode_match = _WORK_MODE_PAT.search(post_exp)
    mode       = mode_match.group(1) if mode_match else ""

    location: str | None = None
    loc_match = _LOCATION_PAT.search(post_exp)
    if loc_match:
        raw_loc = loc_match.group(1).strip().strip(" ,")
        # Ignore WFH pseudo-locations and overly long strings
        if raw_loc and "Home" not in raw_loc and len(raw_loc) < 80:
            location = raw_loc

    # ── 3. Split role / company using the tag-repetition trick ───────────────
    # Find where in post_exp the tags block starts (right after location)
    after_pos = mode_match.end() if mode_match else 0
    if loc_match:
        loc_in_post = post_exp.find(loc_match.group(0))
        if loc_in_post != -1:
            after_pos = max(after_pos, loc_in_post + len(loc_match.group(0)))
    text_after = post_exp[after_pos:].strip()

    words      = pre_exp.split()
    role_title = ""
    company    = ""

    # Try every prefix of pre_exp from longest to shortest.
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i])
        if text_after.lower().startswith(candidate.lower()):
            role_title = candidate.strip()
            company    = " ".join(words[i:]).strip()
            break

    if not role_title:
        mid        = max(1, len(words) // 2)
        role_title = " ".join(words[:mid]).strip()
        company    = " ".join(words[mid:]).strip()

    # Cleanup: remove trailing punctuation
    role_title = role_title.rstrip(" ,").strip()
    company = company.strip().strip(" ,")
    if location:
        location = location.strip().strip(" ,")

    # Heuristic: if company begins with a role-like token, move it into role_title
    ROLE_PREFIXES = {
        "executive", "manager", "intern", "associate", "lead",
        "senior", "junior", "head", "chief", "director", "coordinator"
    }
    if company:
        comp_parts = company.split()
        first_tok = comp_parts[0].lower()
        if first_tok in ROLE_PREFIXES and len(comp_parts) > 1:
            # shift the first token into the role title
            company = " ".join(comp_parts[1:]).strip().strip(" ,")
            role_title = f"{role_title} {comp_parts[0]}".strip()

    if not company or not role_title:
        return None
    # ── 4. Salary / stipend ───────────────────────────────────────────────────
    salary_match = _SALARY_PAT.search(text)
    salary       = salary_match.group(1).strip() if salary_match else None

    # ── 5. Posted date ────────────────────────────────────────────────────────
    posted_match = _POSTED_PAT.search(text)
    posted_at    = posted_match.group(1).strip() if posted_match else None

    # ── 6. Stack tags (job_type + work_mode + opportunity type) ──────────────
    stack: list[str] = []
    jtype_match = _JOB_TYPE_PAT.search(post_exp)
    if jtype_match:
        stack.append(jtype_match.group(1))
    if mode:
        stack.append(mode)
    if "/internships/" in href:
        stack.append("internship")
    elif "/jobs/" in href:
        stack.append("job")

    url = href if href.startswith("http") else f"{BASE_URL}{href}"

    return {
        "company":   company,
        "role":      role_title,
        "source":    "unstop",
        "url":       url,
        "stack":     stack,
        "product":   salary,    # reuse product field for stipend / CTC
        "location":  location,
        "posted_at": posted_at,
    }


# ── Scraper class ─────────────────────────────────────────────────────────────

class UnstopScraper(PlatformScraper):
    """
    Playwright-based scraper for Unstop (unstop.com).

    Scrapes both /jobs and /internships listing pages using numbered
    pagination (?page=N). Each page is loaded once via Playwright to ensure
    Angular hydration completes. No scroll interaction is required.
    """

    source_name = "unstop"

    def __init__(self) -> None:
        # Enforce a minimum 3 s delay between page loads on Unstop
        self._delay: float = max(
            float(os.environ.get("SCRAPER_DELAY_SECONDS", 3)),
            3.0,
        )

    async def scrape(self, role: str, stack: list[str]) -> list[dict[str, Any]]:
        all_jobs:  list[dict[str, Any]] = []
        seen_urls: set[str]             = set()

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

            try:
                for section in _SECTIONS:
                    logger.info("[Unstop] Scraping section: %s", section)

                    for page_num in range(1, MAX_PAGES + 1):
                        url  = f"{BASE_URL}/{section}?page={page_num}"
                        page = await context.new_page()

                        try:
                            logger.info("[Unstop] Loading: %s", url)
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=30_000,
                            )

                            # Wait for at least one card to appear
                            try:
                                await page.wait_for_selector(
                                    _CARD_SEL, timeout=15_000
                                )
                            except PWTimeout:
                                logger.warning(
                                    "[Unstop] No cards on %s — stopping section.", url
                                )
                                break

                            # Brief pause to let Angular finish hydrating
                            await asyncio.sleep(2.0)

                            # ── Extract all listing card links ───────────────
                            links = await page.query_selector_all(_CARD_SEL)
                            logger.info(
                                "[Unstop] %s page %d → %d raw links",
                                section, page_num, len(links),
                            )

                            if not links:
                                break

                            page_count = 0
                            for link_el in links:
                                try:
                                    href = (
                                        await link_el.get_attribute("href") or ""
                                    ).strip()

                                    if not href:
                                        continue

                                    # Skip top-level category pages — listing
                                    # URLs always have at least 2 path segments
                                    # e.g. /jobs/react-developer-pragma-1234
                                    path     = href.split("?")[0].rstrip("/")
                                    segments = [s for s in path.split("/") if s]
                                    if len(segments) < 2:
                                        continue

                                    # Deduplicate by canonical URL (no query string)
                                    canonical = path
                                    if canonical in seen_urls:
                                        continue

                                    text = (await link_el.inner_text()).strip()
                                    job  = _parse_card(href, text)

                                    if job:
                                        seen_urls.add(canonical)
                                        all_jobs.append(job)
                                        page_count += 1

                                except Exception:
                                    logger.debug(
                                        "[Unstop] Error parsing card", exc_info=True
                                    )
                                    continue

                            logger.info(
                                "[Unstop] %s page %d → %d jobs parsed",
                                section, page_num, page_count,
                            )

                            # If this page yielded nothing new, stop paginating
                            if page_count == 0:
                                break

                        except Exception:
                            logger.exception("[Unstop] Unexpected error on %s", url)
                            break

                        finally:
                            await page.close()

                        # Polite delay between page loads
                        if page_num < MAX_PAGES:
                            await asyncio.sleep(self._delay)

            finally:
                await browser.close()

        logger.info("[Unstop] Total scraped: %d opportunities", len(all_jobs))
        return all_jobs