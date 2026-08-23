"""
main.py — FastAPI application and SSE streaming endpoints for the Job Search Agent.

Endpoints:
  GET  /health                  Liveness probe
  POST /search                  Initiate agent search session
  GET  /search/{id}/stream      SSE live stream for progress and jobs
  POST /search/{id}/save        Emit selected jobs to jobs:raw Redis stream
  GET  /searches                Get recent search history
  GET  /searches/{id}           Get search details and results
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import ats_client
import freshness_filter
import intent_parser
import relevance_scorer
import storage
import stream_emitter
from llm_client import LLMClient
from search_executor import SearchExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

llm_client = LLMClient()
search_executor = SearchExecutor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Agent Search Service...")
    await storage.create_pool()
    await stream_emitter.get_redis()
    await llm_client.initialize()
    yield
    await stream_emitter.close_redis()
    await storage.close_pool()
    logger.info("Agent Search Service shut down.")


app = FastAPI(
    title="Job Search Agent Service",
    description="On-demand intent-driven job search agent streaming fresh results live.",
    version="1.0.0",
    lifespan=lifespan,
)


class SearchFilters(BaseModel):
    stack: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    max_age_days: int = 14
    experience_years: Optional[float] = None
    remote: Optional[bool] = False


class SearchRequest(BaseModel):
    query: str
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SaveRequest(BaseModel):
    job_ids: List[str]


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "degraded": llm_client.is_degraded}


@app.post("/search", tags=["search"])
async def create_search(body: SearchRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query string cannot be empty")

    filters_dict = body.filters.model_dump()
    search_id = await storage.create_search(
        query=body.query.strip(),
        filters=filters_dict,
        provider_used=llm_client.provider if not llm_client.is_degraded else "degraded_fallback",
    )
    return {"search_id": search_id}


@app.get("/search/{search_id}/stream", tags=["search"])
async def stream_search_results(search_id: str, request: Request):
    async def event_generator():
        start_time = time.time()
        search = await storage.get_search(search_id)
        if not search:
            yield stream_emitter.format_sse("error", {"message": "Search not found"})
            return

        # Handle reconnection to already completed search
        if search["status"] == "complete":
            stored_results = await storage.get_results(search_id)
            for job in stored_results:
                yield stream_emitter.format_sse("job", job)
            yield stream_emitter.format_sse("done", {})
            return

        try:
            # Step 1: Intent parsing via LLM
            yield stream_emitter.format_sse("progress", {
                "stage": "parsing_intent",
                "message": "Understanding your search...",
            })

            filters = search.get("filters") or {}
            intent = await intent_parser.parse_intent(
                search["query"], filters, llm_client
            )

            await storage.update_search(search_id, parsed_intent=intent)

            yield stream_emitter.format_sse("progress", {
                "stage": "intent_parsed",
                "message": f"Will search {len(intent.get('search_queries', []))} targeted sources",
                "role": intent.get("role"),
                "queries_count": len(intent.get("search_queries", [])),
            })

            # Step 2, 3, 4: Search execution, scoring, and streaming
            seen_urls: set = set()
            total_found = 0
            total_stale = 0
            max_age = filters.get("max_age_days", 14)

            async for item in search_executor.stream_jobs(intent, max_age):
                if item.get("_type") == "progress":
                    yield stream_emitter.format_sse("progress", item)
                else:
                    url = item.get("url", "")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)

                    # Score relevance deterministically
                    item["relevance_score"] = relevance_scorer.score(item, intent)

                    # Save to DB
                    result_id = await storage.save_result(search_id, item)
                    item["id"] = result_id
                    total_found += 1

                    yield stream_emitter.format_sse("job", item)

            duration_ms = int((time.time() - start_time) * 1000)
            await storage.complete_search(search_id, total_found, total_stale, duration_ms)

            yield stream_emitter.format_sse("progress", {
                "stage": "complete",
                "message": f"Found {total_found} relevant jobs",
                "total_found": total_found,
                "discarded_stale": total_stale,
                "search_id": search_id,
            })
            yield stream_emitter.format_sse("done", {})

        except Exception as e:
            logger.exception("Search execution failed for %s: %s", search_id, e)
            await storage.fail_search(search_id)
            yield stream_emitter.format_sse("error", {"message": "Search failed — check service logs"})

    return EventSourceResponse(event_generator())


@app.post("/search/{search_id}/save", tags=["search"])
async def save_jobs_to_pipeline(search_id: str, body: SaveRequest):
    search = await storage.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    saved_count = 0
    for jid in body.job_ids:
        job = await storage.get_result_by_id(jid)
        if job:
            await stream_emitter.emit_job(job)
            await storage.mark_result_saved(jid)
            saved_count += 1

    return {
        "saved": saved_count,
        "message": f"{saved_count} job(s) added to your pipeline",
    }


@app.get("/searches", tags=["history"])
async def list_recent_searches():
    searches = await storage.get_recent_searches(limit=20)
    return searches


@app.get("/searches/{search_id}", tags=["history"])
async def get_search_details(search_id: str):
    search = await storage.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")

    results = await storage.get_results(search_id)
    search["results_count"] = len(results)
    search["sample_results"] = results[:5]
    return search
