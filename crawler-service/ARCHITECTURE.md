# Crawler — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Crawler service runs Scrapy spiders to fetch job listings from public job boards, filters and normalizes items, and emits events to the Redis `jobs:raw` stream for downstream consumption.

## Request / Data Flow

1. Spiders (remotive, wellfound, yc_spider) crawl external job boards and yield job items.
2. Items go through pipelines: deduplication, stack/role filtering, normalization, and emission.
3. `emit_pipeline.py` serializes items and adds them to the Redis stream `jobs:raw` with maxlen capping.

## Internal Execution Pipeline

- `crawler/spiders/*`: spider implementations and parsing logic with `stack_matches()` and `role_matches()` helpers.
- `crawler/pipelines/dedup_pipeline.py`: URL-based deduplication using Redis keys.
- `crawler/pipelines/filter_pipeline.py`: stack/role filtering logic to drop irrelevant items.
- `crawler/pipelines/emit_pipeline.py`: JSON serialization and Redis stream emission.
- `read_stream.py`: utility for tailing or dumping the Redis stream for debugging.

## Important Modules / Files

- `crawler/spiders/*` — spider implementations (remotive, wellfound, yc_spider).
- `crawler/pipelines/*` — deduplication, filtering, and emission pipelines.
- `read_stream.py` — CLI stream monitor.
- `scrapy.cfg` and `crawler/settings.py` — Scrapy project configuration and pipeline ordering.

## Service Interactions

- Emits events to Redis `jobs:raw`, consumed by aggregator-service.
- Uses Playwright for JavaScript-heavy sites and respects politeness settings in `crawler/settings.py`.

## Debugging Notes

- Update selectors when site markup changes; add unit tests for parsing when possible.
- Use `read_stream.py` to inspect emitted events and verify pipeline behavior.
- Playwright and Scrapy timeouts are common failure points; tune delays and concurrency in `crawler/settings.py`.

## Contributor Tips

- Run spiders locally with `scrapy crawl <spider>` for quick parsing checks.
- Add integration tests for critical parsing logic in `crawler/parsers/`.

## Next (Operational) Docs

Operational/runbook content (docker-compose, Playwright setup, quotas) is deferred to a follow-up docs issue.
