# Email Generator Service

## Request/Data Flow

1. `POST /generate` accepts a JSON payload with `template`, optional `job_id`/`contact_id`, candidate details, and context fields.
2. `main.py` initializes the asyncpg pool and fetches job/contact records from PostgreSQL using `storage.py` if IDs are provided.
3. `generator.py` constructs the email context, invokes `ollama_client.py` for product observation generation, and renders Jinja2 templates.
4. Rendered subject/body are inserted into the `emails` table via `storage.insert_email()`, returning the email UUID.
5. `GET /emails` and `GET /emails/{id}` retrieve drafts from PostgreSQL using `storage.py` queries.
6. `POST /emails/{id}/send` resolves the recipient email from the linked contact record, sends via `mailer.py`, and updates `sent_at`/`status` in the database.

## Internal Execution Pipeline

- **Generation Pipeline**: `generator.generate_email()` loads job/contact data, attempts Ollama observation via `ollama_client.generate_observation()`, falls back to YAML-based selection from `fallbacks.yaml`, and renders templates using Jinja2 with context variables.
- **Ollama Integration**: `ollama_client.py` detects available models (mistral/llama3), sends a prompt to `/api/generate`, and returns a single observation sentence or None on failure.
- **Fallback Logic**: `generator._select_fallback()` matches keywords from product/stack against `fallbacks.yaml` categories, selecting a random observation from the best-matched bucket.
- **Template Rendering**: Jinja2 environment in `generator.py` processes templates with variables like `company`, `role`, `your_name`, `product_observation`, and `contact_name`.
- **Storage Operations**: `storage.py` manages asyncpg pool, executes DDL for `jobs`/`contacts`/`emails` tables, and performs CRUD with parameterized queries.
- **Email Sending**: `mailer.send_email()` uses `smtplib.SMTP_SSL` with Gmail credentials, sending plain-text emails and handling authentication errors.

## Important Modules/Files

- `main.py`: FastAPI application with endpoints (`/generate`, `/emails`, `/emails/{id}`, `/emails/{id}/send`), Pydantic models for requests/responses, and lifespan hooks for pool management.
- `generator.py`: Core logic for email creation, including Ollama client calls, fallback selection, and Jinja2 rendering with context assembly.
- `ollama_client.py`: Async HTTP client for Ollama API, model detection via `/api/tags`, and observation generation with timeout handling.
- `mailer.py`: Synchronous Gmail SMTP sender wrapped in `asyncio.run_in_executor`, using SSL on port 465 with App Password authentication.
- `storage.py`: asyncpg pool lifecycle, schema initialization (including `pgcrypto` extension), and CRUD functions for jobs, contacts, and emails tables.
- `fallbacks.yaml`: YAML structure with keyword lists per category (e.g., fintech, devtools) and observation arrays for static fallbacks.
- `templates/`: Directory containing Jinja2 templates (`cold_outreach.j2`, `recruiter_outreach.j2`, `followup.j2`) with conditional rendering and variable substitution.

## Service Interactions

- Reads `jobs` and `contacts` tables from PostgreSQL to populate email templates and resolve recipient addresses.
- Writes to the `emails` table for draft storage and status updates, sharing the database with `aggregator-service` and `contact-discovery-service`.
- Makes HTTP requests to a local Ollama server at `OLLAMA_BASE_URL` for product observations, with automatic fallback to static data.
- Sends outbound emails via Gmail SMTP, requiring external Gmail account configuration for delivery.

## Debugging Notes

- Ollama failures log warnings in `ollama_client.py` for timeouts or HTTP errors, but do not halt generation due to fallback mechanism.
- Database connection issues in `storage.py` raise `RuntimeError` if pool is not initialized, logged during lifespan startup.
- SMTP authentication errors in `mailer.py` propagate as `smtplib.SMTPAuthenticationError`, indicating invalid `GMAIL_APP_PASSWORD`.
- Template rendering errors in `generator.py` raise `ValueError` for unknown templates, logged with template names.
- Asyncpg query timeouts default to 30 seconds in `storage.py`, potentially causing delays in high-load scenarios.
- Fallback selection in `generator.py` logs category scores and selected observations for keyword matching verification.
