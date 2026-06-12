"""
proxy.py — httpx routing helpers for the API Gateway.

Each helper function wraps a specific upstream service.
All calls share a single AsyncClient lifecycle (managed in main.py lifespan).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
from uuid import UUID

import httpx
from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service base URLs — set via environment variables
# ---------------------------------------------------------------------------

def _url(env_var: str, default: str) -> str:
    return os.environ.get(env_var, default).rstrip("/")

AGGREGATOR_URL = _url("AGGREGATOR_URL", "http://aggregator:8000")
SCRAPER_URL    = _url("SCRAPER_URL",    "http://scraper:8001")
CONTACT_URL    = _url("CONTACT_URL",    "http://contact:8002")
EMAIL_GEN_URL  = _url("EMAIL_GEN_URL",  "http://email-gen:8003")

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

# ---------------------------------------------------------------------------
# Shared client (set from lifespan)
# ---------------------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None


def set_client(client: httpx.AsyncClient) -> None:
    global _client
    _client = client


def get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client not initialised.")
    return _client


# ---------------------------------------------------------------------------
# Generic proxy helper
# ---------------------------------------------------------------------------

# Headers that must not be forwarded upstream
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length",   # httpx sets this correctly for the new body
})


async def proxy_request(
    request: Request,
    upstream_url: str,
) -> Response:
    """
    Forward an incoming FastAPI request to *upstream_url* and return
    the upstream response as a FastAPI Response, preserving status code
    and content-type.
    """
    client = get_client()

    # Forward only safe headers
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    body = await request.body()

    try:
        upstream = await client.request(
            method=request.method,
            url=upstream_url,
            headers=forward_headers,
            content=body,
            params=dict(request.query_params),
            timeout=_TIMEOUT,
        )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Upstream unreachable: {upstream_url}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Upstream timeout: {upstream_url}")

    # Strip hop-by-hop from upstream response
    response_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


# ---------------------------------------------------------------------------
# Typed helpers used by the composite workflow endpoint
# ---------------------------------------------------------------------------

async def get_job(job_id: UUID) -> Dict[str, Any]:
    client = get_client()
    resp = await client.get(f"{AGGREGATOR_URL}/jobs/{job_id}", timeout=_TIMEOUT)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    resp.raise_for_status()
    return resp.json()


async def trigger_discovery(company: str, job_id: UUID, roles: list[str]) -> Dict[str, Any]:
    client = get_client()
    resp = await client.post(
        f"{CONTACT_URL}/discover",
        json={"company": company, "job_id": str(job_id), "roles": roles},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


async def get_contacts_for_company(company: str) -> list[Dict[str, Any]]:
    client = get_client()
    resp = await client.get(
        f"{CONTACT_URL}/contacts",
        params={"company": company},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


async def generate_email(
    job_id: UUID,
    contact_id: Optional[UUID],
    template: str,
    referred_by: Optional[str] = None,
) -> Dict[str, Any]:
    client = get_client()
    payload: Dict[str, Any] = {
        "job_id":   str(job_id),
        "template": template,
    }
    if contact_id:
        payload["contact_id"] = str(contact_id)
    if referred_by:
        payload["referred_by"] = referred_by

    resp = await client.post(
        f"{EMAIL_GEN_URL}/generate",
        json=payload,
        timeout=httpx.Timeout(60.0, connect=5.0),  # Ollama may be slow
    )
    resp.raise_for_status()
    return resp.json()


async def health_check(name: str, base_url: str) -> Dict[str, Any]:
    client = get_client()
    try:
        resp = await client.get(f"{base_url}/health", timeout=httpx.Timeout(3.0))
        return {"service": name, "status": "ok" if resp.status_code == 200 else "degraded"}
    except Exception as exc:
        return {"service": name, "status": "unreachable", "detail": str(exc)}
