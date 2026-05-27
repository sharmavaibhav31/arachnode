# Aggregator — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Aggregator service consumes raw job events from a Redis stream, deduplicates and normalizes them, and persists canonical job records to PostgreSQL for downstream services.

## Request / Data Flow

1. Consumer reads from Redis `jobs:raw` stream (consumer groups) and claims pending messages when necessary.
2. Each message is parsed and normalized (company, role, stack, posted_at) and passed to `db.insert_job()`.
3. `db.insert_job()` attempts `INSERT ... ON CONFLICT DO NOTHING` to avoid duplicates; successful inserts set a deduplication key in Redis with a TTL.
4. The service exposes `GET /jobs`, `GET /jobs/{id}`, `PATCH /jobs/{id}/status`, and `GET /stats` for querying aggregated data.

## Internal Execution Pipeline

- `consumer.py`: connection and consumer group management, `run_consumer()` loop, pending message claiming, and batch processing using `XREADGROUP`/`XAUTOCLAIM`.
- `_process_message()`: normalizes payloads, computes dedup key (MD5 of normalized company+role), and invokes `db.insert_job()`.
- `db.py`: asyncpg pool lifecycle, schema setup with GIN/BTREE indexes, and query helpers supporting ILIKE and array GIN containment for stack queries.

## Important Modules / Files

- `main.py` — FastAPI entry, endpoint handlers, lifespan hooks for pool and consumer task management.
- `consumer.py` — Redis stream consumer and message processing logic.
- `db.py` — database schema, pool, and CRUD helpers.
- `models.py` — Pydantic response/request models.

## Service Interactions

- Consumes `jobs:raw` Redis stream emitted by scraper-service.
- Persists canonical job records to PostgreSQL, read by contact-discovery and email-generator services.

## Debugging Notes

- Missing fields in messages are logged and skipped; add extra logging in `_process_message()` for edge cases.
- Database or Redis connectivity issues surface during lifespan startup; verify pool/connection settings and credentials.
- Query timeouts default to 30s; increase when running long analytical queries.

## Contributor Tips

- To test deduplication, craft messages with similar normalized company+role and observe Redis dedup key TTL behavior.
- Add unit tests for `db.insert_job()` when changing schema or uniqueness constraints.

## Next (Operational) Docs

Operational/API usage (example requests, deployment env vars) are deferred to a follow-up docs issue.
