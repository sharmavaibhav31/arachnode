# Contact Discovery — Architecture & Contributor Notes

This file focuses on contributor-oriented/internal architecture information: request/data flow, internal execution pipeline, important modules/files, debugging notes, and service interactions.

## Overview

The Contact Discovery service attempts to discover likely contact emails for a company using public data sources, pattern inference, and SMTP verification, then persists verified contacts to PostgreSQL for downstream use.

## Request / Data Flow

1. `POST /discover` starts a multi-stage pipeline for a given company (optionally with `job_id` and roles).
2. Pipeline stages: domain inference, email pattern detection, name discovery (GitHub/LinkedIn), email construction, SMTP verification.
3. Verified contacts are upserted into PostgreSQL using `storage.upsert_contact()`.
4. API supports querying contacts via `GET /contacts` and deletion via `DELETE /contacts/{id}`.

## Internal Execution Pipeline

- `discovery.py`: orchestrates domain inference, pattern mining, name discovery, and verification.
- `domain_inference()`: Clearbit first, fallback to suffix probes and heuristics.
- `email_pattern_detection()`: mines GitHub/org data and infers common patterns with regex.
- `verifier.py`: MX lookup and SMTP RCPT checks with rate limiting.
- `storage.py`: asyncpg pool and upsert logic with unique constraint on (company, email).

## Important Modules / Files

- `main.py` — FastAPI app and background task wiring.
- `discovery.py` — multi-stage discovery pipeline.
- `verifier.py` — SMTP verification utilities.
- `storage.py` — DB pool and CRUD/upsert helpers.

## Service Interactions

- Reads job records from aggregator-service to link contacts to jobs.
- Persists contacts to PostgreSQL for consumption by email-generator-service.
- Calls external services: Clearbit, GitHub API, LinkedIn scraping, and MX hosts for verification.

## Debugging Notes

- Enable a `GITHUB_TOKEN` to avoid rate limits during name mining; failures are logged but pipeline continues where possible.
- SMTP verification can be noisy; use logging in `verifier.py` to record MX/RCPT outcomes and rate-limiting events.
- Database upsert conflicts are handled by `ON CONFLICT`; add targeted logging when debugging merges.

## Contributor Tips

- Write unit tests for pattern inference when modifying regex or GitHub parsing logic.
- Mock SMTP and DNS responses for deterministic verification tests.

## Next (Operational) Docs

Operational/runbook content (third-party API keys, env vars, deployment) is deferred to a follow-up docs issue.
