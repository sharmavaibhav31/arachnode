# Gateway Service

## Request/Data Flow

1. Proxy routes (/api/jobs/*, /api/scrape, /api/contacts/*, /api/emails/*) forward requests to aggregator, scraper, contact-discovery, and email-generator services using httpx.
2. `GET /api/health` fans out health checks to all four services concurrently, returning aggregated status.
3. `GET /api/summary` reads scheduler run summary from shared volume at /data/run_summary.json.
4. `POST /api/workflow/apply` orchestrates composite workflow: fetches job, triggers contact discovery, retrieves contacts, generates email draft.
5. `GET /` serves dashboard.html as a single-page application.

## Internal Execution Pipeline

- **Proxying**: `proxy.proxy_request()` forwards method, headers (excluding hop-by-hop), body, and query params to upstream, returning Response with preserved status/content-type.
- **Health Fan-out**: `main.gateway_health()` uses `asyncio.gather()` for parallel health checks, aggregating results into JSON response.
- **Composite Workflow**: `main.workflow_apply()` calls `proxy.get_job()`, `proxy.trigger_discovery()`, `proxy.get_contacts_for_company()`, `proxy.generate_email()` sequentially, handling exceptions.
- **Dashboard Serving**: `main.dashboard()` returns FileResponse for dashboard.html, which uses JavaScript to call /api/* endpoints.

## Important Modules/Files

- `main.py`: FastAPI application with proxy routes, composite workflow endpoint, health fan-out, and dashboard serving.
- `proxy.py`: httpx client management, generic proxy_request() helper, typed service helpers for workflow orchestration.
- `dashboard.html`: Single-page dashboard SPA with tabs for jobs, contacts, emails, stats, using Chart.js and fetch API for /api/* calls.

## Service Interactions

- Proxies requests to aggregator-service (jobs/stats), scraper-service (scrape), contact-discovery-service (contacts/discover), email-generator-service (emails/generate).
- Reads scheduler run summary from shared Docker volume.
- Serves dashboard that consumes all /api/* endpoints.

## Debugging Notes

- Proxy timeouts logged as 503/504 HTTPExceptions, with upstream URL in detail.
- Health check failures logged in aggregated response, with unreachable services marked.
- Workflow orchestration logs exceptions per step, raising HTTPException on failures.
- Dashboard JavaScript errors not logged server-side, debug via browser console.
- Shared volume read errors for summary logged as 500 responses.
- Concurrent health checks may have varying response times, aggregated in single JSON.
