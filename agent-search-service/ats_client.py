"""
ats_client.py — ATS detection and direct public JSON API fetching.

Ports and async-enables ATS detection and fetching logic for Lever, Greenhouse,
and Ashby from crawler-service/crawler/parsers/ats_detector.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

ATS_PATTERNS = {
    "lever": lambda url: "jobs.lever.co" in url,
    "greenhouse": lambda url: "boards.greenhouse.io" in url or "grnh.se" in url,
    "ashby": lambda url: "jobs.ashbyhq.com" in url,
    "workday": lambda url: "myworkdayjobs.com" in url,
}


def detect_ats(url: str) -> str:
    for name, matcher in ATS_PATTERNS.items():
        if matcher(url):
            return name
    return "generic"


def extract_company_slug(url: str, ats: str) -> Optional[str]:
    try:
        parts = urlparse(url).path.strip("/").split("/")
        if ats in ("lever", "greenhouse", "ashby") and parts:
            return parts[0]
    except Exception:
        pass
    return None


async def fetch_lever_jobs(company_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """Fetch jobs via Lever API: https://api.lever.co/v0/postings/{company}?mode=json"""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        close_client = True

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        postings = resp.json()
    except Exception as e:
        logger.debug("[Lever] Failed for %s: %s", company_slug, e)
        return []
    finally:
        if close_client:
            await client.aclose()

    results = []
    for job in postings:
        categories = job.get("categories", {})
        results.append({
            "company": company_slug.replace("-", " ").title(),
            "role": job.get("text", ""),
            "team": categories.get("team", ""),
            "location": categories.get("location", ""),
            "url": job.get("hostedUrl", ""),
            "posted_at": _ms_to_iso(job.get("createdAt")),
            "stack": job.get("tags", []),
            "source": "lever_api",
        })
    return results


async def fetch_greenhouse_jobs(company_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """Fetch jobs via Greenhouse API: https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs?content=true"
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        close_client = True

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug("[Greenhouse] Failed for %s: %s", company_slug, e)
        return []
    finally:
        if close_client:
            await client.aclose()

    results = []
    for job in data.get("jobs", []):
        location = job.get("location", {}).get("name", "")
        dept = job.get("departments", [{}])[0].get("name", "") if job.get("departments") else ""
        results.append({
            "company": company_slug.replace("-", " ").title(),
            "role": job.get("title", ""),
            "team": dept,
            "location": location,
            "url": job.get("absolute_url", ""),
            "posted_at": job.get("updated_at"),
            "stack": [],
            "source": "greenhouse_api",
        })
    return results


async def fetch_ashby_jobs(company_slug: str, client: Optional[httpx.AsyncClient] = None) -> List[Dict[str, Any]]:
    """Fetch jobs via Ashby public GraphQL endpoint."""
    url = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobBoardWithTeams"
    payload = {
        "operationName": "ApiJobBoardWithTeams",
        "variables": {"organizationHostedJobsPageName": company_slug},
        "query": """
          query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
            jobBoard: jobBoardWithTeams(
              organizationHostedJobsPageName: $organizationHostedJobsPageName
            ) {
              jobPostings { id title locationName jobPostingState isRemote externalLink }
            }
          }
        """,
    }
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        close_client = True

    try:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("data", {}).get("jobBoard", {}).get("jobPostings", [])
    except Exception as e:
        logger.debug("[Ashby] Failed for %s: %s", company_slug, e)
        return []
    finally:
        if close_client:
            await client.aclose()

    results = []
    for p in postings:
        if p.get("jobPostingState") == "Published":
            results.append({
                "company": company_slug.replace("-", " ").title(),
                "role": p.get("title", ""),
                "location": p.get("locationName", "Remote" if p.get("isRemote") else ""),
                "url": p.get("externalLink") or f"https://jobs.ashbyhq.com/{company_slug}/{p.get('id')}",
                "posted_at": None,
                "stack": [],
                "source": "ashby_api",
            })
    return results


def _ms_to_iso(ms_timestamp: Any) -> Optional[str]:
    if not ms_timestamp:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromtimestamp(int(ms_timestamp) / 1000, tz=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None
