"""
scrapers/base.py — Abstract base class for all platform scrapers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


def matches_roles(title: str, roles: list[str]) -> bool:
    """
    Returns True if the job title contains any target role
    phrase as a substring (case-insensitive, whole phrase).
    """
    if not roles:
        return True
    title_lower = title.lower()
    return any(r.lower() in title_lower for r in roles)


def matches_stack(job_stack: list[str], target_stack: list[str]) -> bool:
    """
    Returns True if there is any overlap between the job's
    listed skills and the target stack.
    If target_stack is empty, everything passes.
    If job has no stack listed, it passes (we can't reject 
    what we can't see).
    """
    if not target_stack:
        return True
    if not job_stack:
        return True   # no stack info = don't reject, just pass
    job_lower = {s.lower().strip() for s in job_stack}
    target_lower = {s.lower().strip() for s in target_stack}
    return bool(job_lower.intersection(target_lower))


class PlatformScraper(ABC):
    """
    Contract every platform scraper must implement.

    scrape() returns a list of dicts, each matching the JobPosting
    event schema consumed by the aggregator service:

        company    str
        role       str
        source     str
        url        str
        stack      list[str]   (serialised to JSON by the emitter)
        product    str | None
        location   str | None
        posted_at  str | None  (ISO-8601 string or None)
    """

    # Scrapers set this to identify themselves in stream events
    source_name: str = "unknown"

    @abstractmethod
    async def scrape(self, roles: list[str], stack: list[str]) -> list[dict[str, Any]]:
        """
        Scrape jobs for *roles* on *stack* and return a list of raw job dicts.
        Each dict must have at minimum 'company', 'role', and 'url' set.
        """
        ...
