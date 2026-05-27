# Scheduler — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Scheduler service runs periodic cycles (scrape, discover, draft) using APScheduler to orchestrate scraping, contact discovery, and draft generation pipelines.

## Request / Data Flow

1. `run_scrape_cycle()` triggers scrapers via the Gateway and runs Scrapy subprocesses, then measures job deltas.
2. `run_discover_cycle()` fetches new jobs and calls contact-discovery for each job with appropriate delays.
3. `run_draft_cycle()` fetches jobs, verifies contacts, and calls email-generator to draft messages.
4. After each run, a summary JSON is written to `/data/run_summary.json` for observability.

## Internal Execution Pipeline

- `main.py`: APScheduler setup, interval jobs, manual run dispatch, and summary writing.
- `tasks.py`: synchronous task implementations that call gateway endpoints and manage subprocesses for scraping.
- `logger.py`: structured JSON logging for tasks and error context.

## Important Modules / Files

- `main.py` — scheduler lifecycle and job registration.
- `tasks.py` — scrape/discover/draft task implementations.
- `logger.py` — JSONFormatter and structured logging utilities.

## Service Interactions

- Calls gateway endpoints to trigger scraping, discovery, and generation.
- Runs Scrapy subprocesses for crawler-service when applicable.
- Writes run summaries to shared volume consumed by gateway.

## Debugging Notes

- Inspect `/data/run_summary.json` to see per-run stats and recorded errors.
- Subprocess stderr and HTTP errors are captured in the summary for post-mortem analysis.
- Use manual runs for isolated testing of individual tasks.

## Contributor Tips

- Adjust intervals and delays in env vars when testing locally to avoid rate limits.
- Use manual dispatch to reproduce issues without waiting for scheduled runs.

## Next (Operational) Docs

Operational/runbook content (cron tuning, deployment) is deferred to a follow-up docs issue.
