# Scraper — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Scraper service runs platform-specific scrapers (Naukri, LinkedIn, Internshala), normalizes job listings, and emits events to the Redis `jobs:raw` stream for downstream processing.

## Request / Data Flow

1. `POST /scrape` triggers background scraping for the requested role/stack.
2. Each platform scraper yields job dictionaries that are normalized and validated.
3. `emit.emit_job()` serializes and pushes jobs to Redis `jobs:raw` with maxlen capping.

## Internal Execution Pipeline

- `main._run_all_scrapers()` runs scrapers concurrently with `asyncio.gather()` and collects results.
- `scrapers/*` implement the platform-specific scraping and parsing logic.
- `emit.py` handles Redis emission and normalization.

## Important Modules / Files

- `main.py` — FastAPI endpoint and background task orchestration.
- `emit.py` — Redis emitter and normalization.
- `scrapers/` — platform-specific scrapers and `base.py` contract.

## Service Interactions

- Emits job events to Redis `jobs:raw` for aggregator-service consumption.
- Uses Playwright for JS-heavy pages and honors politeness and concurrency settings.

## Debugging Notes

- Monitor Playwright selector changes and update parsing logic accordingly.
- Use logs to inspect per-platform job counts and emission errors.

## Contributor Tips

- Run individual scrapers locally for focused debugging and selector iteration.
- Add unit tests for parsing when updating selectors.

## Next (Operational) Docs

Operational/runbook content (Playwright setup, credentials, Docker compose) is deferred to a follow-up docs issue.
