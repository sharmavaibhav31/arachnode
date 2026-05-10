# Email Generator Service

## Purpose of the service

This service drafts personalized cold emails for job outreach, stores those drafts in PostgreSQL, and can send them through Gmail SMTP. It combines Jinja2 templates with an optional local Ollama LLM observation and falls back to `fallbacks.yaml` when Ollama is unavailable.

## Request/Data Flow

1. `POST /generate` receives a request with `template`, optional `job_id` / `contact_id`, candidate details, and context.
2. `main.py` opens the database pool and resolves job/contact records from PostgreSQL via `storage.py`.
3. `generator.py` prepares the email context, attempts to generate a product observation through `ollama_client.py`, and renders one of the Jinja2 templates.
4. The rendered subject/body are persisted to the `emails` table with `storage.insert_email()`.
5. Clients can query drafts with `GET /emails` and `GET /emails/{id}`.
6. `POST /emails/{id}/send` looks up the linked contact email, sends the message with `mailer.py`, and updates `sent_at` / status.

## Important Files/Modules

- `main.py` — FastAPI app, endpoints, lifecycle hooks, request/response models.
- `generator.py` — email generation pipeline, Ollama fallback logic, Jinja2 rendering.
- `ollama_client.py` — async Ollama REST client and remote model detection.
- `mailer.py` — Gmail SMTP sender using `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`.
- `storage.py` — asyncpg pool management, schema initialization, CRUD for `jobs`, `contacts`, and `emails`.
- `fallbacks.yaml` — domain-based static product observations.
- `templates/` — Jinja2 templates for `cold_outreach`, `recruiter_outreach`, and `followup`.

## Local Execution

### Run locally with Python

```bash
cd email-generator-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql://jobuser:jobpass@localhost:5432/jobsdb"
export GMAIL_ADDRESS="you@gmail.com"
export GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"
export YOUR_NAME="Your Name"
export YOUR_GITHUB_URL="https://github.com/yourhandle"

uvicorn main:app --reload --port 8003
```

### Run with Docker

```bash
docker build -t email-generator .
docker run \
  -e DATABASE_URL="postgresql://jobuser:jobpass@host.docker.internal:5432/jobsdb" \
  -e OLLAMA_BASE_URL="http://host.docker.internal:11434" \
  -e GMAIL_ADDRESS="you@gmail.com" \
  -e GMAIL_APP_PASSWORD="abcd efgh ijkl mnop" \
  -e YOUR_NAME="Your Name" \
  -e YOUR_GITHUB_URL="https://github.com/yourhandle" \
  -p 8003:8000 \
  email-generator
```

### Verify service start

Open <http://localhost:8003/docs> for FastAPI interactive docs.

## Environment Variables

- `DATABASE_URL` — PostgreSQL DSN used by asyncpg.
- `OLLAMA_BASE_URL` — Ollama API base URL; defaults to `http://localhost:11434`.
- `GMAIL_ADDRESS` — Gmail address used as the sender.
- `GMAIL_APP_PASSWORD` — Gmail App Password used for SMTP login.
- `YOUR_NAME` — sender name used in rendered emails and SMTP `From`.
- `YOUR_GITHUB_URL` — GitHub profile URL included in emails.
- `GRADUATION_YEAR` — optional fallback graduation year used by templates when not provided in payload.

## Service Interactions

- Uses PostgreSQL to read `jobs` and `contacts` records and to store `emails` drafts.
- Reads `jobs` / `contacts` tables from the same database, so it can work with `aggregator-service` and `contact-discovery-service` if they share the same PostgreSQL instance.
- Calls a local Ollama server to generate a single product observation sentence, with static fallback observations from `fallbacks.yaml` if Ollama is unavailable.
- Sends outbound mail through Gmail SMTP on port `465`.

## Debugging/Setup Notes

- `DATABASE_URL` is required before the service can start; `storage.py` creates `jobs`, `contacts`, and `emails` tables automatically.
- `OLLAMA_BASE_URL` defaults to `http://localhost:11434`; missing Ollama does not break generation because `fallbacks.yaml` is used.
- Gmail sending requires a valid `GMAIL_APP_PASSWORD` and must use an App Password, not the normal Gmail login password.
- The service uses `pgcrypto` for `gen_random_uuid()`, so PostgreSQL must allow extension creation.
- `mailer.py` performs SMTP over SSL; connection failures usually indicate network/blocking or invalid credentials.
- If `YOUR_NAME` or `YOUR_GITHUB_URL` are not supplied in the request, the service falls back to environment values.

## Example Requests/Workflows

### Generate a cold outreach email

```bash
curl -X POST http://localhost:8003/generate \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "contact_id": "a1b2c3d4-0000-0000-0000-000000000001",
    "template": "cold_outreach",
    "your_name": "Vaibhav Sharma",
    "your_stack": ["Python", "FastAPI", "PostgreSQL"],
    "github_url": "https://github.com/sharmavaibhav31",
    "graduation_year": 2025
  }'
```

### Fetch emails for a job

```bash
curl "http://localhost:8003/emails?job_id=3fa85f64-5717-4562-b3fc-2c963f66afa6"
```

### Fetch a single email draft

```bash
curl http://localhost:8003/emails/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

### Update status

```bash
curl -X PATCH http://localhost:8003/emails/f47ac10b-.../status \
  -H "Content-Type: application/json" \
  -d '{"status": "replied"}'
```

### Send a generated email

```bash
curl -X POST http://localhost:8003/emails/f47ac10b-.../send
```
