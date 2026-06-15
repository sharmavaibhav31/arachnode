"""
Search provider orchestration for Google dork discovery.

External APIs are optional. If no provider is configured, the service still
returns generated queries so the flow is testable without a paid dependency.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol

from .dork_builder import DorkBuilder, JobDorkConfig
from .dork_filter import DiscoveryCandidate, DiscoveryFilter, RawSearchResult


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int = 10) -> list[RawSearchResult]:
        ...


class SerperSearchProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, limit: int = 10) -> list[RawSearchResult]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": query, "num": limit},
            )
            response.raise_for_status()

        payload = response.json()
        organic = payload.get("organic") or []
        return [
            RawSearchResult(
                title=item.get("title") or "",
                url=item.get("link") or "",
                snippet=item.get("snippet") or "",
                query=query,
            )
            for item in organic
        ]


class GoogleCseSearchProvider:
    def __init__(self, api_key: str, cx: str) -> None:
        self.api_key = api_key
        self.cx = cx

    async def search(self, query: str, limit: int = 10) -> list[RawSearchResult]:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": self.api_key, "cx": self.cx, "q": query, "num": limit},
            )
            response.raise_for_status()

        payload = response.json()
        return [
            RawSearchResult(
                title=item.get("title") or "",
                url=item.get("link") or "",
                snippet=item.get("snippet") or "",
                query=query,
            )
            for item in payload.get("items") or []
        ]


class SeedSearchProvider:
    """
    Local fallback for demos/tests. DORK_SEED_RESULTS should be JSON shaped as:
    [{"title": "...", "url": "...", "snippet": "..."}]
    """

    def __init__(self, results: list[dict[str, str]]) -> None:
        self.results = results

    async def search(self, query: str, limit: int = 10) -> list[RawSearchResult]:
        return [
            RawSearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                query=query,
            )
            for item in self.results[:limit]
        ]


def provider_from_env() -> SearchProvider | None:
    serper_key = os.environ.get("SERPER_API_KEY")
    if serper_key:
        return SerperSearchProvider(serper_key)

    google_key = os.environ.get("GOOGLE_CSE_API_KEY")
    google_cx = os.environ.get("GOOGLE_CSE_ID")
    if google_key and google_cx:
        return GoogleCseSearchProvider(google_key, google_cx)

    seed_json = os.environ.get("DORK_SEED_RESULTS")
    if seed_json:
        return SeedSearchProvider(json.loads(seed_json))

    return None


@dataclass(frozen=True)
class DiscoveryResponse:
    queries: list[str]
    candidates: list[DiscoveryCandidate]


class DorkDiscoveryService:
    def __init__(
        self,
        provider: SearchProvider | None = None,
        builder: DorkBuilder | None = None,
        result_filter: DiscoveryFilter | None = None,
    ) -> None:
        self.provider = provider
        self.builder = builder or DorkBuilder()
        self.result_filter = result_filter or DiscoveryFilter()

    async def discover(
        self,
        config: JobDorkConfig,
        results_per_query: int = 10,
    ) -> DiscoveryResponse:
        queries = self.builder.build(config)
        if not self.provider:
            return DiscoveryResponse(queries=queries, candidates=[])

        candidates: list[DiscoveryCandidate] = []
        for query in queries:
            raw_results = await self.provider.search(query, limit=results_per_query)
            for result in raw_results:
                decision = self.result_filter.evaluate(result)
                if decision.accepted and decision.candidate:
                    candidates.append(decision.candidate)

        return DiscoveryResponse(queries=queries, candidates=candidates)
