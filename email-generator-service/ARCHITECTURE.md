# Email Generator — Architecture & Contributor Notes

This file is focused on contributor-oriented/internal architecture information: request/data flow, service interactions, important modules/files, debugging notes, and the internal execution pipeline.

## Overview

The Email Generator service creates draft outreach emails from job/contact records and template prompts, optionally enriching content via a local Ollama model. It stores drafts in PostgreSQL and can send messages via SMTP.

## Request / Data Flow

1. External caller (gateway or CLI) triggers generation by calling the service endpoint or invoking the internal API surface.
2. The service loads context data from PostgreSQL (`jobs`, `contacts`) when `job_id` or `contact_id` are provided.
3. `generator.generate_email()` builds a rendering context (company, role, stack, candidate details, your_name, etc.).
4. The service requests a short `product_observation` from Ollama via `ollama_client.py`. On failure it falls back to static observations from `fallbacks.yaml`.
5. Jinja2 templates in `templates/` render subject and body using the assembled context.
6. The rendered draft is persisted to the `emails` table via `storage.insert_email()` and an email UUID is returned.
7. Sending (`/emails/{id}/send`) resolves recipient from the contact record and hands the message to `mailer.send_email()` to perform SMTP delivery and update status fields.

## Internal Execution Pipeline

- `main.py`: FastAPI app; registers endpoints and manages lifespan events (DB pool lifecycle).
- `generator.py`: Central orchestration — loads DB rows, calls Ollama client, applies fallback selection, renders templates, and calls `storage` to persist drafts.
- `ollama_client.py`: Async client that probes available models and posts prompts to the local Ollama API with timeouts and retries.
- `storage.py`: Manages `asyncpg` pool, schema initialization, and CRUD helpers for `jobs`, `contacts`, and `emails`.
- `mailer.py`: Synchronous SMTP sender wrapped via `asyncio.run_in_executor` for non-blocking behavior.

Execution details:
- Generation attempts Ollama first; fallback is deterministic based on keyword scoring against entries in `fallbacks.yaml`.
- Template rendering uses a small, trusted set of variables — avoid adding unvalidated user input into template context.

## Important Modules / Files

- `main.py` — app entry; endpoints: `/generate`, `/emails`, `/emails/{id}`, `/emails/{id}/send`.
- `generator.py` — build context, call Ollama, select fallback, render templates.
- `ollama_client.py` — model detection and single-observation generation.
- `storage.py` — asyncpg pool and CRUD functions.
- `mailer.py` — SMTP send logic.
- `fallbacks.yaml` — curated static observations keyed by category.
- `templates/` — Jinja2 templates used for rendering.

## Service Interactions

- Reads `jobs` and `contacts` from the shared PostgreSQL instance.
- Writes drafts and status updates to the `emails` table.
- Calls a local Ollama server (`OLLAMA_BASE_URL`) for short product observations.
- Sends outbound mail via external SMTP (configured via environment variables).

## Debugging Notes

- Ollama timeouts and HTTP errors are logged in `ollama_client.py`; generation continues using fallbacks.
- If the DB pool is not initialized, `storage` raises `RuntimeError` during lifespan — check logs at startup.
- SMTP authentication failures raise `smtplib.SMTPAuthenticationError` — verify credentials and App Password.
- Template rendering errors surface as `jinja2` exceptions; test templates locally with a small context for quicker iteration.

## Contributor Tips

- Local testing: run unit tests in `tests/unit` and integration tests in `tests/integration` as applicable.
- To debug generation flow: add temporary logging in `generator.generate_email()` around Ollama calls and fallback selection.
- Keep `fallbacks.yaml` categories small and focused; add a unit test when adding new categories to ensure predictable selection.

## Next (Operational) Docs

Operational/API usage (endpoint examples, env var setup, deployment notes) are intentionally deferred to a follow-up docs issue to avoid duplication across services. If you need an operational snapshot now, inspect `main.py` and the Pydantic models used for requests/responses.
