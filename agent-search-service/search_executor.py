"""
search_executor.py — Parallel search execution across web search and ATS APIs.

Runs targeted search queries concurrently using a semaphore. Leverages duckduckgo-search
for primary URL discovery, ATS APIs (Lever, Greenhouse, Ashby) for structured extraction,
and HTTP page fetching as fallback.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

import httpx

import ats_client
from freshness_filter import filter_by_freshness

logger = logging.getLogger(__name__)


def _search_duckduckgo_sync(query: str) -> List[Dict[str, Any]]:
    """Synchronous call to duckduckgo-search DDGS.text()."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=10, timelimit="m"))
    except Exception as e:
        logger.warning("DuckDuckGo search error for query '%s': %s", query[:40], e)
        return []


class SearchExecutor:
    async def stream_jobs(
        self,
        intent: Dict[str, Any],
        max_age_days: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes all search queries concurrently (max 4 parallel).
        Yields SSE progress events and individual job posting candidate dicts.
        """
        queries = intent.get("search_queries", [])
        total = len(queries)
        if not queries:
            return

        yield {
            "_type": "progress",
            "stage": "searching",
            "message": f"Running {total} targeted searches in parallel...",
            "queries_total": total,
            "queries_done": 0,
        }

        semaphore = asyncio.Semaphore(4)
        seen_urls: Set[str] = set()
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        done_counter = [0]

        async def worker(query: str) -> None:
            async with semaphore:
                try:
                    jobs = await self._execute_query(query, seen_urls, max_age_days)
                    for job in jobs:
                        await queue.put({"type": "job", "data": job})
                except Exception as e:
                    logger.warning("Query worker failed for '%s': %s", query[:30], e)
                finally:
                    done_counter[0] += 1
                    await queue.put({
                        "type": "progress",
                        "data": {
                            "_type": "progress",
                            "stage": "searching",
                            "message": f"Searched {done_counter[0]} of {total} sources...",
                            "queries_total": total,
                            "queries_done": done_counter[0],
                        }
                    })

        tasks = [asyncio.create_task(worker(q)) for q in queries]

        # Process queue until all tasks complete
        completed_tasks = 0
        while completed_tasks < total:
            msg = await queue.get()
            if msg["type"] == "progress":
                completed_tasks = msg["data"]["queries_done"]
                yield msg["data"]
            elif msg["type"] == "job":
                yield msg["data"]

        # Flush any remaining items in queue
        while not queue.empty():
            msg = queue.get_nowait()
            if msg["type"] == "job":
                yield msg["data"]

        # Ensure all worker tasks are cleaned up
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_query(
        self,
        query: str,
        seen_urls: Set[str],
        max_age_days: int,
    ) -> List[Dict[str, Any]]:
        """Execute one query via DuckDuckGo and resolve returned URLs."""
        search_results = await asyncio.to_thread(_search_duckduckgo_sync, query)
        raw_jobs: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as http_client:
            for result in search_results:
                url = result.get("href", "") or result.get("link", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                job = await self._extract_job_from_url(url, result, http_client)
                if job:
                    job["search_query"] = query
                    raw_jobs.append(job)

        kept_jobs, _ = filter_by_freshness(raw_jobs, max_age_days)
        return kept_jobs

    async def _extract_job_from_url(
        self,
        url: str,
        search_result: Dict[str, Any],
        http_client: httpx.AsyncClient,
    ) -> Optional[Dict[str, Any]]:
        """Extract structured job info using ATS detection or page fallback."""
        ats = ats_client.detect_ats(url)
        slug = ats_client.extract_company_slug(url, ats)

        if ats == "lever" and slug:
            jobs = await ats_client.fetch_lever_jobs(slug, http_client)
            matching = [j for j in jobs if j.get("url") == url]
            if matching:
                return matching[0]
            if jobs:
                candidate = dict(jobs[0])
                candidate["url"] = url
                return candidate

        elif ats == "greenhouse" and slug:
            jobs = await ats_client.fetch_greenhouse_jobs(slug, http_client)
            matching = [j for j in jobs if j.get("url") == url]
            if matching:
                return matching[0]
            if jobs:
                candidate = dict(jobs[0])
                candidate["url"] = url
                return candidate

        elif ats == "ashby" and slug:
            jobs = await ats_client.fetch_ashby_jobs(slug, http_client)
            matching = [j for j in jobs if j.get("url") == url]
            if matching:
                return matching[0]
            if jobs:
                candidate = dict(jobs[0])
                candidate["url"] = url
                return candidate

        # Web search generic fallback
        title = search_result.get("title", "")
        snippet = search_result.get("body", "") or search_result.get("snippet", "")

        company = ""
        role = title

        if " at " in title:
            parts = title.split(" at ", 1)
            role = parts[0].strip()
            company = parts[1].strip().split(" - ")[0].split(" | ")[0]
        elif " - " in title:
            parts = title.split(" - ", 1)
            role = parts[0].strip()
            company = parts[1].strip().split(" | ")[0]
        elif " | " in title:
            parts = title.split(" | ", 1)
            role = parts[0].strip()
            company = parts[1].strip()

        # Clean title artifacts
        role = re.sub(r'\s*\([^)]*\)', '', role).strip()

        return {
            "company": company or "Unknown Company",
            "role": role or "Job Opening",
            "stack": [],
            "location": "",
            "posted_at": None,
            "url": url,
            "source": "web_search",
        }
