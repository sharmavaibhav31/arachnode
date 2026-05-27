# Gateway — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Gateway service proxies API requests to backend services, aggregates health/status, and orchestrates composite workflows that involve multiple services.

## Request / Data Flow

1. Client requests hit proxy endpoints (e.g., `/api/jobs`, `/api/scrape`, `/api/contacts`, `/api/emails`) which forward requests to the appropriate backend service.
2. Health checks fan out to multiple services concurrently and return aggregated status.
3. Composite workflow (`/api/workflow/apply`) sequences downstream calls: fetch job, trigger discovery, fetch contacts, generate email draft.

## Internal Execution Pipeline

- `proxy.py`: httpx-based forwarding helper that preserves headers and body while stripping hop-by-hop headers.
- `main.py`: endpoints for proxying, health fan-out (asyncio.gather), workflow orchestration, and dashboard serving.

## Important Modules / Files

- `main.py` — FastAPI entry and workflow orchestration.
- `proxy.py` — generic `proxy_request()` and typed helpers for downstream services.
- `dashboard.html` — dashboard SPA that consumes `/api/*` endpoints.

## Service Interactions

- Proxies to aggregator-service, scraper-service, contact-discovery-service, and email-generator-service.
- Reads scheduler run summary from shared volume for `/api/summary`.

## Debugging Notes

- Proxy timeouts surface as 503/504 with upstream URL in logs.
- Workflow orchestration logs per-step exceptions; increase logging for problematic steps when reproducing bugs.

## Contributor Tips

- Use the gateway to run end-to-end workflows locally by wiring services to local ports and invoking `/api/workflow/apply`.

## Next (Operational) Docs

Operational/runbook content (CORS, TLS, deployment) is deferred to a follow-up docs issue.
