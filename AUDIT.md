# JobHunter — Full Technical Audit Report
Generated: 2026-06-19
Audited by: AntiGravity architectural analysis

---

## 1. Executive Summary

JobHunter (codenamed Arachnode) is an event-driven microservice system designed to automate the top-of-funnel pipeline for software engineering job applications. It crawls startup directories and job platforms, deduplicates job postings using a Redis stream and a PostgreSQL database, performs OSINT-based contact discovery using the GitHub API and LinkedIn search, and automatically generates personalized cold outreach emails via Jinja2 and local LLMs (Ollama). The system solves the problem of manual tracking, candidate discovery, and boilerplate email drafting for bulk job searching.

Currently, the codebase is in a highly functional but partially hardened state. The core orchestration, including the Redis stream pub/sub mechanism, PostgreSQL data persistence, API gateway, and individual services for scraping and email generation, are fully built. There is a background scheduler that automates sweeps. New features like resume parsing, an Unstop scraper, weekly email digests, and follow-up email logic have been added beyond the initial plan. However, some aspects remain partially built or incomplete: there is a critical bug where the scheduler tries to run Scrapy spiders in a subprocess without having `scrapy` installed, contact discovery Playwright binaries are improperly cached in Docker, and there is zero authentication protecting the exposed API endpoints.

Overall, the architecture demonstrates a mature, scalable decoupling of concerns through bounded contexts and asynchronous event handling. The code quality is generally high, utilizing Python 3.11 features, Pydantic validation, and async I/O. However, the system is not entirely ready for open-source contributors without addressing the missing end-to-end tests, Docker dependency bugs, and the complete lack of API authentication, which poses a severe security risk if deployed to a public VPS.

---

## 2. Repository Structure

```text
jobCrawler/
├── .claude/                             # Claude agent instruction files — COMPLETE
│   └── agents/                          # 24 agent profiles for different QA/auditing tasks — COMPLETE
├── aggregator-service/                  # Jobs aggregator and deduplicator — COMPLETE
│   ├── consumer.py                      # Background Redis stream consumer — COMPLETE
│   ├── db.py                            # asyncpg PostgreSQL adapter — COMPLETE
│   ├── Dockerfile                       # Multi-stage Docker build — COMPLETE
│   ├── main.py                          # FastAPI endpoints for jobs and stats — COMPLETE
│   ├── matcher.py                       # Semantic ranking utility — COMPLETE
│   ├── models.py                        # Pydantic schemas — COMPLETE
│   ├── requirements.txt                 # Python dependencies — COMPLETE
│   ├── test_matcher.py                  # Unit tests for matcher — COMPLETE
│   └── utils/                           # Helper utilities (date_utils.py) — COMPLETE
├── contact-discovery-service/           # OSINT contact discovery — COMPLETE
│   ├── discovery.py                     # Pipeline: domains, emails, GitHub & LinkedIn scraping — COMPLETE
│   ├── Dockerfile                       # Docker build (Buggy Playwright cache) — PARTIAL
│   ├── main.py                          # FastAPI endpoints — COMPLETE
│   ├── requirements.txt                 # Python dependencies — COMPLETE
│   ├── storage.py                       # asyncpg PostgreSQL adapter — COMPLETE
│   └── verifier.py                      # SMTP validation with rate limits — COMPLETE
├── crawler-service/                     # Scrapy-based web crawlers — COMPLETE
│   ├── crawler/
│   │   ├── spiders/                     # Scrapy spiders
│   │   │   ├── base_spider.py           # Base startup spider class — COMPLETE
│   │   │   ├── cutshort_spider.py       # Cutshort spider — COMPLETE
│   │   │   ├── github_org_spider.py     # GitHub Org spider — COMPLETE
│   │   │   ├── glassdoor.py             # Glassdoor spider — COMPLETE
│   │   │   ├── remotive_spider.py       # Remotive spider — COMPLETE
│   │   │   ├── wellfound_spider.py      # Wellfound spider — COMPLETE
│   │   │   └── yc_spider.py             # YC Jobs spider — COMPLETE
│   ├── Dockerfile                       # Docker build (Runs as root) — PARTIAL
│   ├── read_stream.py                   # Helper to read from Redis stream — COMPLETE
│   ├── run_local.sh                     # Bash script for local execution — COMPLETE
│   ├── scrapy.cfg                       # Scrapy configuration — COMPLETE
│   └── tests/                           # Tests for the crawler — PARTIAL (Only ATS detector)
├── email-generator-service/             # Cold email draft generator — COMPLETE
│   ├── Dockerfile                       # Multi-stage Docker build — COMPLETE
│   ├── fallbacks.yaml                   # Fallback text strings — COMPLETE
│   ├── generator.py                     # Email generation orchestration — COMPLETE
│   ├── generator_digest.py              # Weekly digest generation — COMPLETE
│   ├── mailer.py                        # Gmail SMTP sender — COMPLETE
│   ├── main.py                          # FastAPI endpoints (resume upload, digest) — COMPLETE
│   ├── ollama_client.py                 # Local LLM wrapper — COMPLETE
│   ├── resume_parser.py                 # Resume parsing logic — COMPLETE
│   ├── storage.py                       # asyncpg PostgreSQL adapter — COMPLETE
│   ├── templates/                       # Jinja2 templates for emails — COMPLETE
│   ├── test_resume_parser.py            # Unit tests for resume parser — COMPLETE
│   └── RESUME_PARSER_EXAMPLES.md        # Examples of personalized emails — COMPLETE
├── gateway/                             # Unified API Gateway and Proxy — COMPLETE
│   ├── dashboard.html                   # Single-page Vanilla JS Dashboard — COMPLETE
│   ├── Dockerfile                       # Docker build — COMPLETE
│   ├── main.py                          # FastAPI router fanout and workflows — COMPLETE
│   └── proxy.py                         # httpx request forwarding — COMPLETE
├── scheduler/                           # APScheduler automation pipelines — COMPLETE
│   ├── Dockerfile                       # Docker build (Missing scrapy dependency) — PARTIAL
│   ├── logger.py                        # Custom JSON logger — COMPLETE
│   ├── main.py                          # APScheduler background daemon — COMPLETE
│   └── tasks.py                         # Tasks for scrape, discover, draft, digest, followup — COMPLETE
├── scraper-service/                     # On-demand Playwright scrapers — COMPLETE
│   ├── discovery/                       # Dork builder utilities — COMPLETE
│   ├── Dockerfile                       # Multi-stage Docker build (Correct Playwright cache) — COMPLETE
│   ├── emit.py                          # Shared Redis stream emitter — COMPLETE
│   ├── main.py                          # FastAPI endpoints — COMPLETE
│   ├── scrapers/                        # Platform scrapers
│   │   ├── base.py                      # Base scraper class — COMPLETE
│   │   ├── google_dork.py               # Google Dork scraper — COMPLETE
│   │   ├── internshala.py               # Internshala scraper — COMPLETE
│   │   ├── linkedin.py                  # LinkedIn scraper — COMPLETE
│   │   ├── naukri.py                    # Naukri scraper — COMPLETE
│   │   └── unstop.py                    # Unstop scraper — COMPLETE
│   ├── tests/                           # Unit tests — PARTIAL
│   └── UNSTOP.md                        # Documentation for Unstop scraper — COMPLETE
├── tests/                               # Cross-service tests — PARTIAL
│   ├── contract/                        # JSON schema validation tests — COMPLETE
│   ├── integration/                     # Redis and Postgres integration tests — COMPLETE
│   ├── unit/                            # Independent service logic tests — COMPLETE
│   └── conftest.py                      # Pytest fixtures — COMPLETE
├── workflows/                           # GitHub Issue/PR templates — COMPLETE
├── docker-compose.yml                   # Infrastructure orchestrator — PARTIAL (missing volumes, depends_on)
└── README.md                            # Comprehensive documentation — COMPLETE
```

---

## 3. Services Inventory

### Crawler Service
- **Status:** COMPLETE
- **Language and framework:** Python / Scrapy
- **Port:** None (Runs as a one-shot process)
- **Entry point file:** `crawler-service/crawler/spiders/*` (via Scrapy CLI)
- **What it does:** Navigates startup directories (YC, Remotive, Wellfound, etc.), extracts job listings using XPath/CSS selectors, and publishes items as JSON payloads to the `jobs:raw` Redis stream.
- **What is working:** Successfully scrapes flat HTML and emits structured data.
- **What is broken or incomplete:** Fails to run automatically inside the Scheduler container due to a missing Scrapy dependency and inaccessible project paths. Container runs as root.
- **External dependencies it calls:** Redis (publishes to stream).
- **What calls it:** Called via the `docker run` equivalent or as a subprocess by the Scheduler (currently broken).
- **Known issues or code smells spotted during audit:** It runs as `root` in Docker. Test coverage is nearly non-existent.

### Platform Scraper Service
- **Status:** COMPLETE
- **Language and framework:** Python / FastAPI / Playwright
- **Port:** 8001
- **Entry point file:** `scraper-service/main.py`
- **What it does:** Handles on-demand JavaScript-heavy browser scraping for platforms like LinkedIn, Naukri, Internshala, and Unstop. Runs them concurrently via a BackgroundTask and emits normalized job entities to the Redis stream.
- **What is working:** The FastAPI endpoints and Playwright scrapers function as intended, successfully emitting jobs to Redis.
- **What is broken or incomplete:** Google Dorks discovery is implemented but noted as "demo-friendly" without emitting jobs.
- **External dependencies it calls:** Redis (publishes to stream).
- **What calls it:** API Gateway (`POST /api/scrape`).
- **Known issues or code smells spotted during audit:** Playwright runs with `--no-sandbox`. 

### Aggregator Service
- **Status:** COMPLETE
- **Language and framework:** Python / FastAPI / asyncpg / redis-py
- **Port:** 8000
- **Entry point file:** `aggregator-service/main.py`
- **What it does:** Runs a background asyncio consumer loop to read from the `jobs:raw` Redis stream, deduplicates jobs using MD5 hashes of the normalized company and role, and persists them into PostgreSQL. Exposes a queryable REST API for job analytics and listings.
- **What is working:** Redis consumer group mechanics, database idempotent insertions, and query filtering.
- **What is broken or incomplete:** Semantic ranking (resume parsing) logic is handled on read (`GET /jobs?resume=`), which could become slow on large data sets since it recalculates ranks on the fly.
- **External dependencies it calls:** Redis (Stream reading), PostgreSQL (CRUD operations).
- **What calls it:** API Gateway (routes `/api/jobs/*`).
- **Known issues or code smells spotted during audit:** Missing pagination metadata in the API response (returns a flat list up to `limit`).

### Contact Discovery Service
- **Status:** COMPLETE
- **Language and framework:** Python / FastAPI / httpx / Playwright
- **Port:** 8002
- **Entry point file:** `contact-discovery-service/main.py`
- **What it does:** Uses OSINT techniques to find recruiter and engineering manager contacts for a specific company. It infers domains via Clearbit, detects email patterns via GitHub commit logs, scrapes names from LinkedIn and GitHub orgs, and validates emails via SMTP probes.
- **What is working:** The entire pipeline logic, rate-limited SMTP verification, and asynchronous PostgreSQL persistence.
- **What is broken or incomplete:** The Dockerfile runs `playwright install` as root before the `USER appuser` directive, causing the Playwright binary to be placed in an inaccessible cache folder for the runtime user. 
- **External dependencies it calls:** PostgreSQL, Clearbit Autocomplete API, GitHub API, LinkedIn, arbitrary SMTP servers.
- **What calls it:** API Gateway (`POST /api/discover` and `/api/workflow/apply`).
- **Known issues or code smells spotted during audit:** LinkedIn scraping is highly susceptible to authwalls. Rate limit dictionary (`_domain_rate`) is in-memory, meaning it won't sync if scaled horizontally. 

### Email Generator Service
- **Status:** COMPLETE
- **Language and framework:** Python / FastAPI / Ollama / Jinja2
- **Port:** 8003
- **Entry point file:** `email-generator-service/main.py`
- **What it does:** Evaluates Jinja2 templates, interacts with a local Ollama instance for LLM-powered context mapping, parses PDF/TXT resumes to build candidate context, drafts personalized cold emails, stores drafts in PostgreSQL, and sends emails via Gmail SMTP.
- **What is working:** Resume parsing, email generation, template rendering, and SMTP dispatch.
- **What is broken or incomplete:** Currently only supports sending via a hardcoded `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`.
- **External dependencies it calls:** PostgreSQL, Ollama (local/remote), Gmail SMTP (port 465).
- **What calls it:** API Gateway (`POST /api/generate`, `/api/emails/*`, `/api/workflow/apply`, `/api/digest`).
- **Known issues or code smells spotted during audit:** The `POST /resume` endpoint takes a file upload directly but has no authorization, allowing arbitrary file uploads (though limited to 5MB and not written to disk).

### Gateway Service
- **Status:** COMPLETE
- **Language and framework:** Python / FastAPI / httpx / Vanilla JS
- **Port:** 8080
- **Entry point file:** `gateway/main.py`
- **What it does:** Acts as the unified public proxy for all internal microservices. It forwards requests via `httpx`, hosts the static `dashboard.html` single-page application, and manages the composite `POST /api/workflow/apply` endpoint.
- **What is working:** Request proxying, dashboard serving, and cross-service orchestration.
- **What is broken or incomplete:** It is entirely unauthenticated. 
- **External dependencies it calls:** Aggregator, Scraper, Contact Discovery, and Email Generator services.
- **What calls it:** User via Web Browser, Scheduler Service.
- **Known issues or code smells spotted during audit:** API is completely open to the network.

### Scheduler Service
- **Status:** PARTIAL
- **Language and framework:** Python / APScheduler / httpx
- **Port:** None (Background daemon)
- **Entry point file:** `scheduler/main.py`
- **What it does:** Runs timed automation sweeps. Every 8 hours it triggers scrapers and local Scrapy spiders. Every 24 hours it discovers contacts for new jobs and drafts emails. Weekly, it sends an email digest. Daily, it drafts follow-ups.
- **What is working:** Job scheduling, offset execution, weekly digests, and follow-ups.
- **What is broken or incomplete:** The `run_scrape_cycle` attempts to execute `subprocess.run(["scrapy", "crawl", spider])` inside the scheduler container. However, `scrapy` is not installed in the scheduler's `requirements.txt`, and the crawler directory is not mounted by default.
- **External dependencies it calls:** Gateway Service (`GET/POST` via HTTP).
- **What calls it:** Self-triggered based on chron intervals.
- **Known issues or code smells spotted during audit:** Subprocess execution is an anti-pattern in Dockerized microservices. The scheduler should instead trigger the Crawler container or expose an endpoint on the crawler.

---

## 4. Database Schema

### Complete schema as SQL

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS jobs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company     TEXT        NOT NULL,
    role        TEXT        NOT NULL,
    source      TEXT,
    url         TEXT,
    stack       TEXT[],
    product     TEXT,
    location    TEXT,
    posted_at   TIMESTAMPTZ,
    status      TEXT        NOT NULL DEFAULT 'new',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contacts (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     UUID        REFERENCES jobs(id) ON DELETE SET NULL,
    company    TEXT        NOT NULL,
    domain     TEXT,
    name       TEXT,
    email      TEXT,
    role       TEXT,
    source     TEXT,
    verified   TEXT        NOT NULL DEFAULT 'unverified',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT contacts_company_email_key UNIQUE (company, email)
);

CREATE TABLE IF NOT EXISTS emails (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id       UUID        REFERENCES jobs(id) ON DELETE SET NULL,
    contact_id   UUID        REFERENCES contacts(id) ON DELETE SET NULL,
    template     TEXT        NOT NULL,
    subject      TEXT        NOT NULL,
    body         TEXT        NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at      TIMESTAMPTZ,
    status       TEXT        NOT NULL DEFAULT 'draft'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_jobs_stack ON jobs USING GIN (stack);
CREATE INDEX IF NOT EXISTS idx_jobs_posted_at ON jobs (posted_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts (company);
CREATE INDEX IF NOT EXISTS idx_contacts_job_id ON contacts (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_job_id ON emails (job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_contact_id ON emails (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_emails_status ON emails (status);
```

### Schema diagram (ASCII)

```text
┌────────────────────────┐
│          jobs          │
├────────────────────────┤
│ id (UUID) [PK]         │◄────────┐
│ company (TEXT)         │         │
│ role (TEXT)            │         │
│ source (TEXT)          │         │
│ url (TEXT)             │         │
│ stack (TEXT[])         │         │
│ product (TEXT)         │         │
│ location (TEXT)        │         │
│ posted_at (TIMESTAMPTZ)│         │
│ status (TEXT)          │◄────┐   │
│ created_at (TIMESTAMPTZ│     │   │
└──────────┬─────────────┘     │   │
           │                   │   │
           │                   │   │
┌──────────┴─────────────┐     │   │
│        contacts        │     │   │
├────────────────────────┤     │   │
│ id (UUID) [PK]         │◄─┐  │   │
│ job_id (UUID) [FK]     │──┘  │   │
│ company (TEXT)         │     │   │
│ domain (TEXT)          │     │   │
│ name (TEXT)            │     │   │
│ email (TEXT)           │     │   │
│ role (TEXT)            │     │   │
│ source (TEXT)          │     │   │
│ verified (TEXT)        │     │   │
│ created_at (TIMESTAMPTZ│     │   │
└──────────┬─────────────┘     │   │
           │                   │   │
           │                   │   │
┌──────────┴─────────────┐     │   │
│         emails         │     │   │
├────────────────────────┤     │   │
│ id (UUID) [PK]         │     │   │
│ job_id (UUID) [FK]     │─────│───┘
│ contact_id (UUID) [FK] │─────┘
│ template (TEXT)        │
│ subject (TEXT)         │
│ body (TEXT)            │
│ generated_at(TIMESTAMP)│
│ sent_at (TIMESTAMPTZ)  │
│ status (TEXT)          │
└────────────────────────┘
```

### Schema assessment
- Are indexes appropriate for the query patterns in the code? Yes, GIN indexes are efficiently utilized for array overlap operations on the `stack` array. Partial indexes on `job_id`, `contact_id`, and `email` appropriately map the API access patterns.
- Are there missing indexes that would cause slow queries? There is no index on `jobs.company` despite contact discovery frequently filtering by it. Contact discovery queries use `WHERE company ILIKE $1`, which scans the entire table regardless of an index, but an exact match query on `company` would benefit from an index.
- Are there any N+1 query patterns in the codebase? Yes. The composite `POST /api/workflow/apply` endpoint runs distinct queries per service rather than taking advantage of relational joins, acting as a serialized N+1 over HTTP.
- Are foreign key constraints enforced or just implied? They are explicitly enforced at the database level using `ON DELETE SET NULL`.
- What schema changes have been made since the original design? No migration tool (like Alembic) is used. The schema is defined as idempotent DDL in `db.py` and `storage.py` across services.

---

## 5. API Endpoints — Complete Reference

### [GET] /api/health
- Service: Gateway (fans out to all services)
- Status: WORKING
- Purpose: Provides a complete system liveness check.
- Request body: None
- Query parameters: None
- Response schema: `{"gateway": "ok", "services": [...]}`
- Calls: Aggregator `/health`, Scraper `/health`, Contact `/health`, Email-Gen `/health`.
- Known issues: Returns 207 Multi-Status if any internal service is down, which is good API design, but it will block synchronously waiting for unresponsive services to timeout.

### [GET] /api/summary
- Service: Gateway
- Status: WORKING
- Purpose: Returns the most recent JSON run summary produced by the scheduler.
- Request body: None
- Query parameters: None
- Response schema: JSON file payload from disk.
- Calls: Local filesystem (`/data/run_summary.json`).
- Known issues: Will crash if the file is locked or malformed since there is no file locking mechanism between the Scheduler and the Gateway.

### [GET] /api/jobs
- Service: Aggregator
- Status: WORKING
- Purpose: List and filter jobs.
- Request body: None
- Query parameters: `role` (str), `stack` (str), `status` (str), `sort` (str: 'latest', 'oldest'), `limit` (int), `resume` (str).
- Response schema: `List[JobOut]`
- Calls: PostgreSQL `jobs` table.
- Known issues: The `resume` parameter triggers a blocking `rank_jobs(jobs, resume)` semantic sorting pass, which can stall the async loop.

### [GET] /api/jobs/export
- Service: Aggregator
- Status: WORKING
- Purpose: Export filtered jobs as CSV.
- Request body: None
- Query parameters: `role` (str), `stack` (str), `status` (str), `sort` (str), `format` (str).
- Response schema: `StreamingResponse` (CSV text)
- Calls: PostgreSQL `jobs` table.
- Known issues: None. Efficient chunked iteration is used.

### [GET] /api/jobs/{id}
- Service: Aggregator
- Status: WORKING
- Purpose: Fetch a single job.
- Request body: None
- Query parameters: None
- Response schema: `JobOut`
- Calls: PostgreSQL `jobs` table.
- Known issues: None.

### [PATCH] /api/jobs/{id}/status
- Service: Aggregator
- Status: WORKING
- Purpose: Update job application status.
- Request body: `{"status": "new|applied|ignored"}`
- Query parameters: None
- Response schema: `JobOut`
- Calls: PostgreSQL `jobs` table.
- Known issues: None.

### [GET] /api/stats
- Service: Aggregator
- Status: WORKING
- Purpose: Aggregate counts by source and status.
- Request body: None
- Query parameters: None
- Response schema: `StatsOut`
- Calls: PostgreSQL `jobs` table.
- Known issues: Uses `COUNT(*)` over the entire table without time bounds, which will become slow at scale.

### [POST] /api/scrape
- Service: Scraper
- Status: WORKING
- Purpose: Trigger all scraping scripts concurrently.
- Request body: `{"role": "string", "stack": ["string"]}`
- Query parameters: None
- Response schema: `ScrapeResponse`
- Calls: Playwright browser scripts, Redis Stream (`jobs:raw`).
- Known issues: Runs as a FastAPI BackgroundTask but returns immediately; the caller receives no feedback on actual success or failure.

### [POST] /api/discover
- Service: Contact
- Status: WORKING
- Purpose: Find contacts for a company.
- Request body: `{"company": "string", "job_id": "UUID", "roles": ["string"], "domain": "string"}`
- Query parameters: None
- Response schema: `{"triggered": true, "company": "...", "message": "..."}`
- Calls: Clearbit API, GitHub API, LinkedIn, arbitrary SMTP servers, PostgreSQL `contacts` table.
- Known issues: Extensive third-party calls executed in the background without retry logic.

### [GET] /api/contacts
- Service: Contact
- Status: WORKING
- Purpose: List contacts for a company.
- Request body: None
- Query parameters: `company` (str, required)
- Response schema: `List[ContactOut]`
- Calls: PostgreSQL `contacts` table.
- Known issues: Filters via `ILIKE %company%` which causes a full table scan.

### [GET] /api/contacts/{job_id}
- Service: Contact
- Status: WORKING
- Purpose: List contacts associated directly with a job.
- Request body: None
- Query parameters: None
- Response schema: `List[ContactOut]`
- Calls: PostgreSQL `contacts` table.
- Known issues: None.

### [DELETE] /api/contacts/{id}
- Service: Contact
- Status: WORKING
- Purpose: Delete a specific contact.
- Request body: None
- Query parameters: None
- Response schema: 204 No Content
- Calls: PostgreSQL `contacts` table.
- Known issues: None.

### [POST] /api/generate
- Service: Email-Gen
- Status: WORKING
- Purpose: Generate a personalized email.
- Request body: `GenerateRequest` (template, candidate parameters, job/contact ids).
- Query parameters: None
- Response schema: `GenerateResponse`
- Calls: PostgreSQL `jobs` and `contacts` tables, Ollama REST API.
- Known issues: Evaluates LLM completion directly inside the request/response lifecycle. Long inference times will cause API timeouts.

### [GET] /api/emails
- Service: Email-Gen
- Status: WORKING
- Purpose: List emails for a given job.
- Request body: None
- Query parameters: `job_id` (UUID, required)
- Response schema: `List[EmailOut]`
- Calls: PostgreSQL `emails` table.
- Known issues: None.

### [GET] /api/emails/{id}
- Service: Email-Gen
- Status: WORKING
- Purpose: Fetch a specific email.
- Request body: None
- Query parameters: None
- Response schema: `EmailOut`
- Calls: PostgreSQL `emails` table.
- Known issues: None.

### [PATCH] /api/emails/{id}/status
- Service: Email-Gen
- Status: WORKING
- Purpose: Manually update an email's status.
- Request body: `{"status": "draft|sent|replied"}`
- Query parameters: None
- Response schema: `EmailOut`
- Calls: PostgreSQL `emails` table.
- Known issues: None.

### [POST] /api/emails/{id}/send
- Service: Email-Gen
- Status: WORKING
- Purpose: Send a generated email via Gmail.
- Request body: None
- Query parameters: None
- Response schema: `EmailOut`
- Calls: PostgreSQL `contacts` table, Gmail SMTP server.
- Known issues: Blocking operation executed in thread-pool.

### [POST] /api/workflow/apply
- Service: Gateway
- Status: WORKING
- Purpose: Execute the discovery-to-draft orchestration synchronously.
- Request body: `{"job_id": "UUID", "template": "...", "roles": ["..."]}`
- Query parameters: None
- Response schema: `{"job": {...}, "contacts": [...], "draft_email": {...}}`
- Calls: Aggregator GET, Contact POST, Contact GET, Email-Gen POST.
- Known issues: Implements an arbitrary `asyncio.sleep(3)` to wait for background discovery. Highly fragile and prone to race conditions if discovery takes longer than 3 seconds.

| Method | Path | Service | Status |
|--------|------|---------|--------|
| GET | /api/health | Gateway | WORKING |
| GET | /api/summary | Gateway | WORKING |
| GET | /api/jobs | Aggregator | WORKING |
| GET | /api/jobs/export | Aggregator | WORKING |
| GET | /api/jobs/{id} | Aggregator | WORKING |
| PATCH | /api/jobs/{id}/status | Aggregator | WORKING |
| GET | /api/stats | Aggregator | WORKING |
| POST | /api/scrape | Scraper | WORKING |
| POST | /api/discover | Contact | WORKING |
| GET | /api/contacts | Contact | WORKING |
| GET | /api/contacts/{id} | Contact | WORKING |
| DELETE | /api/contacts/{id} | Contact | WORKING |
| POST | /api/generate | Email-Gen | WORKING |
| GET | /api/emails | Email-Gen | WORKING |
| GET | /api/emails/{id} | Email-Gen | WORKING |
| PATCH | /api/emails/{id}/status | Email-Gen | WORKING |
| POST | /api/emails/{id}/send | Email-Gen | WORKING |
| POST | /api/workflow/apply | Gateway | WORKING |

---

## 6. Data Flow Analysis

### Primary pipeline flow
1. Scheduler triggers the crawler at specified intervals (or user triggers via `POST /api/scrape`).
2. Playwright and Scrapy scrapers fetch platforms, parse HTML, and build an intermediary Python dictionary.
3. The scraper's `emit.py` normalizes fields and publishes JSON payloads to the `jobs:raw` Redis stream via `XADD`.
4. The Aggregator service runs an `XREADGROUP` consumer loop. It reads the stream, normalizes the company and role to generate an MD5 deduplication hash (`dedup:agg:hash`).
5. If the hash doesn't exist in Redis, the Aggregator saves the job to the PostgreSQL `jobs` table and `XACK`s the message.
6. The Scheduler executes a discovery sweep, calling `POST /api/discover` for new jobs.
7. The Contact service receives the job, finds contacts, validates their emails, and stores them in the `contacts` table (linked via `job_id`).
8. The Scheduler executes a drafting sweep, calling `POST /api/generate`.
9. The Email service fetches candidate context, requests Ollama LLM completion, maps Jinja2 templates, and inserts a draft into the `emails` table.
10. The user clicks "Send" on the Dashboard, invoking `POST /api/emails/{id}/send`, which fires an SMTP request to Gmail and updates the DB status to 'sent'.

### Redis Streams
- **Stream name(s) found in the code:** `jobs:raw`
- **Producer services and what they emit:** `scraper-service` and `crawler-service` emit normalized dictionary representations of job postings.
- **Consumer services and what they do with messages:** `aggregator-service` verifies duplication logic via MD5 hash lookups on Redis and inserts non-duplicates into PostgreSQL.
- **Consumer group configuration:** Group `aggregator-group`, consumer `aggregator-1`. Uses `XAUTOCLAIM` to recover failed messages.
- **Current maxlen setting and whether it is appropriate:** `maxlen=50_000` approximate. Appropriate for a personal data funnel.
- **Any message loss risk identified:** Low. Messages are only `XACK`ed *after* successful Postgres insertion.

### Data transformation map

| Field | Crawler output | Redis Stream | After aggregator | API response |
|-------|---------------|--------------|-----------------|--------------|
| id | N/A | N/A | UUID | UUID |
| company | str | JSON string | TEXT | str |
| role | str | JSON string | TEXT | str |
| source | str | JSON string | TEXT | str |
| url | str | JSON string | TEXT | str |
| stack | list[str] | JSON string array | TEXT[] | list[str] |
| product | str | JSON string | TEXT | str |
| location | str | JSON string | TEXT | str |
| posted_at | None / str | JSON string | TIMESTAMPTZ | str (ISO format) |
| status | N/A | N/A | TEXT | str ('new'/'applied'/'ignored') |
| created_at | N/A | N/A | TIMESTAMPTZ | str (ISO format) |

---

## 7. New Features Added by Contributors

### Unstop Scraper
- **Added by:** Unknown contributor.
- **What it does:** Scrapes both `/jobs` and `/internships` on unstop.com. Uses Playwright to render the Angular SPA.
- **Files changed or added:** `scraper-service/scrapers/unstop.py`, `scraper-service/run_unstop.py`, `scraper-service/UNSTOP.md`, `tests/unit/test_unstop_parser.py`, `scraper-service/main.py`
- **How it integrates with the existing architecture:** Integrated into the `/scrape` endpoint concurrently with other Playwright scrapers.
- **Test coverage:** Yes (Unit tests in `tests/unit/test_unstop_parser.py`)
- **Documentation:** Yes (`UNSTOP.md` provided).

### Resume Parser
- **Added by:** Unknown contributor (Planned feature completed).
- **What it does:** Accepts PDF/TXT file uploads, parses candidate context (skills, experience, role), and pipes context into Ollama/Jinja2 to hyper-personalize generated drafts.
- **Files changed or added:** `email-generator-service/resume_parser.py`, `email-generator-service/main.py`, `email-generator-service/test_resume_parser.py`, `email-generator-service/RESUME_PARSER_EXAMPLES.md`
- **How it integrates with the existing architecture:** Exposed via `POST /resume` endpoint to fetch JSON context. Data is passed into `POST /generate`.
- **Test coverage:** Yes (`test_resume_parser.py`)
- **Documentation:** Yes (`RESUME_PARSER_EXAMPLES.md`).

### Weekly Digest
- **Added by:** Unknown contributor.
- **What it does:** Computes a week label and drafts a weekly email summary of discovered jobs. Sent out every Sunday via APScheduler.
- **Files changed or added:** `email-generator-service/generator_digest.py`, `scheduler/tasks.py` (added `run_digest_cycle`), `scheduler/main.py`
- **How it integrates with the existing architecture:** Exposed via `POST /digest` on the Email service. Triggers SMTP immediately without saving drafts to the database.
- **Test coverage:** Partial
- **Documentation:** No

### Follow-up Reminder Drafting
- **Added by:** Unknown contributor.
- **What it does:** Automatically checks the database for emails sent > `FOLLOWUP_DAYS` (7 days) ago and drafts follow-up templates if no replies were noted.
- **Files changed or added:** `scheduler/tasks.py` (added `run_followup_cycle`), `scheduler/main.py`
- **How it integrates with the existing architecture:** Uses existing `/api/emails` and `/api/generate` endpoints via Gateway API.
- **Test coverage:** No
- **Documentation:** No

---

## 8. Architecture Changes

- **Services added beyond the original plan:** None explicitly, though the `.claude/agents/` directory indicates Claude AI agents are heavily integrated as an orchestration layer for codebase monitoring, auditing, and maintenance.
- **Services that were merged or split:** The original 7-service design is still fully intact.
- **Architectural patterns that changed:** None major. The codebase strictly adhered to the REST API / Redis event stream duality. 
- **New infrastructure components introduced:** None. 
- **Any architectural debt introduced:** The Scheduler service executes `subprocess.run(["scrapy", "crawl", spider])`. This heavily couples the daemon scheduler to the crawler binaries. Furthermore, the `docker-compose.yml` mounts do not support this, so the container errors out entirely when it attempts to run Scrapy.

### Updated architecture diagram (ASCII)

```text
                                                  ┌────────────────────────┐
┌─────────────────────┐   Jobs via REST POST      │                        │
│                     ├──────────────────────────►│    Gateway Service     │
│  Scheduler Service  │                           │        (:8080)         │
│    (APScheduler)    │   Trigger operations      │                        │
└──────────┬──────────┘                           └──────┬────────┬────────┘
           │                                             │        │
           │ Trigger spiders via POST               REST │        │ REST
           │                                             │        │
┌──────────▼──────────┐                           ┌──────▼────────▼────────┐
│                     │      Jobs via POST        │                        │
│  Platform Scraper   ├──────────────────────────►│   Aggregator Service   │
│      (:8001)        │                           │        (:8000)         │
└─────────────────────┘                           └──────┬─────────────────┘
                                                         │        ▲
┌─────────────────────┐      Jobs via Stream             │        │ Store
│                     │                           ┌──────▼────────▼────────┐
│   Crawler Service   ├──────[ Redis ]───────────►│      PostgreSQL        │
│   (Scrapy spider)   │        Stream             │      Database DB       │
└─────────────────────┘                           └──────┬────────┬────────┘
                                                         │        │
┌─────────────────────┐                           ┌──────▼────────▼────────┐
│                     │  Trigger via REST POST    │                        │
│    Email Service    ◄───────────────────────────┤   Contact Discovery    │
│       (:8003)       │                           │        (:8002)         │
└───────┬─────────────┘                           └────────────────────────┘
        │
┌───────▼─────────────┐
│ Ollama Local LLM /  │
│ Gmail SMTP Gateway  │
└─────────────────────┘
```

---

## 9. Docker & Infrastructure Audit

### Per-Dockerfile assessment
- **Aggregator Service**: Standard Python 3.11 slim. `appuser` implemented correctly. 
- **Contact Discovery Service**: Implements Playwright. `appuser` is implemented *after* `playwright install chromium` without explicit path declarations. Binaries are locked out of the runtime user's accessibility. 
- **Crawler Service**: Does not implement `appuser` at all. Runs as root. Unnecessary `wget`, `curl`, `gnupg` packages installed for Chrome but Playwright handles this cleanly.
- **Email Generator Service**: Clean. `appuser` implemented correctly.
- **Gateway**: Clean. `appuser` implemented correctly.
- **Scheduler**: Implements `appuser`. Missing `scrapy` in `requirements.txt`, meaning it cannot trigger subprocesses.
- **Scraper Service**: Perfectly implements `appuser` with explicit `PLAYWRIGHT_BROWSERS_PATH` cache adjustments to securely share Playwright binaries.

### docker-compose assessment
- **Are all services present?** Yes.
- **Are healthchecks defined and correct?** Yes, standard `curl` and `pg_isready` operations.
- **Are depends_on relationships correct and complete?** Missing `postgres` requirement for `crawler` (but crawler actually doesn't use postgres, only redis). Gateway appropriately depends on everything. 
- **Are environment variables wired correctly between services?** Mostly yes. Missing `redis_data` volume map.
- **Are volumes defined for persistent data (Postgres, Redis)?** Postgres was mapped to `pgdata`, but Redis data persistence wasn't mounted anywhere locally.
- **Are ports correctly mapped and documented?** Yes.
- **Will docker-compose up actually start the full system successfully in its current state?** It will start, but the scheduler will crash on Scrapy subprocess executions, and Contact Discovery Playwright scraping will error out due to binary permission issues. 

---

## 10. Test Coverage Report

| Service | Unit tests | Integration tests | Contract tests | E2E tests | Overall |
|---------|------------|-------------------|----------------|-----------|---------|
| crawler | ✓ partial  | ✗ missing         | ✗ missing      | ✗ missing | 10%     |
| scraper | ✓ partial  | ✗ missing         | ✓ complete     | ✗ missing | 30%     |
| aggregator | ✓ complete | ✓ complete     | ✓ complete     | ✗ missing | 80%     |
| contact | ✗ missing  | ✗ missing         | ✗ missing      | ✗ missing | 0%      |
| email-gen | ✓ partial| ✗ missing         | ✗ missing      | ✗ missing | 20%     |
| gateway | ✗ missing  | ✗ missing         | ✗ missing      | ✗ missing | 0%      |
| scheduler | ✗ missing | ✗ missing        | ✗ missing      | ✗ missing | 0%      |

**Five most critical missing tests:**
1. **Contact Discovery E2E:** Requires network mock handling to simulate GitHub and Clearbit endpoints. This system dictates pipeline conversion.
2. **Gateway E2E Routing tests:** Given the gateway proxies the entire stack, unit tests testing httpx orchestration rules are paramount.
3. **Contact Discovery Data insertion:** Validating deduplication constraint handling in Postgres across edge cases.
4. **Email Generation LLM fallback:** Assuring Ollama API disconnection safely yields to Jinja2 backup templates.
5. **Scheduler Process mocking:** Assuring APScheduler instances successfully boot and cycle without dying silently on arbitrary subprocess failures.

---

## 11. Open Issues & Known Bugs

### [Scheduler Subprocess Crash]
- **Severity**: CRITICAL
- **File and line**: `scheduler/tasks.py:118`
- **Description**: Scheduler runs `subprocess.run(["scrapy", "crawl", spider])`. Scrapy is not installed in the scheduler's Docker container.
- **Suggested fix**: Eject Scrapy from the Scheduler entirely. Hit an HTTP endpoint on a Crawler container daemon, or use Docker's API to spin up ephemeral crawler containers.

### [Contact Discovery Playwright Binary Permissions]
- **Severity**: HIGH
- **File and line**: `contact-discovery-service/Dockerfile:28`
- **Description**: `playwright install` runs before `USER appuser`. The binaries land in `/root/.cache/ms-playwright` which `appuser` cannot read.
- **Suggested fix**: Mimic the approach in `scraper-service/Dockerfile` which sets `ENV PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright` and runs `chown`.

### [Gateway Arbitrary Sleep Race Condition]
- **Severity**: HIGH
- **File and line**: `gateway/main.py:231`
- **Description**: `await asyncio.sleep(3)` assumes background contact discovery is complete within 3 seconds. It almost certainly won't be on the first run for a given company due to rate limits.
- **Suggested fix**: Replace arbitrary sleep with a polling loop, or utilize WebSockets for real-time pushing.

### [In-Memory Discovery Rate Limits]
- **Severity**: MEDIUM
- **File and line**: `contact-discovery-service/verifier.py:39`
- **Description**: Uses an in-memory dictionary to track rate limiting per domain (`_domain_rate`). If Docker replicas scale horizontally, rate limits will desync.
- **Suggested fix**: Migrate rate-limiting logic to Redis `INCR` and `EXPIRE`.

### [Missing Pagination Meta-Data]
- **Severity**: LOW
- **File and line**: `aggregator-service/main.py:105`
- **Description**: The `GET /jobs` endpoint simply returns a list of dictionaries up to the arbitrary `limit`. No metadata is provided regarding total database records.
- **Suggested fix**: Wrap API response in a JSON envelope providing `total_count` and `next_page` cursors.

---

## 12. Continuation Roadmap

### Immediate (fix before next contributor onboarding)
1. Rewrite `contact-discovery-service/Dockerfile` Playwright installation rules.
2. Fix Scheduler Scrapy crash by altering orchestration parameters.
3. Implement basic network authorization via API keys on the Gateway routing configuration.

### Short term (next 2-4 weeks)
1. Add pagination to the `/jobs` and `/contacts` endpoints.
2. Rewrite the arbitrary `asyncio.sleep` workflow into a pub-sub UI event.
3. Replace the `contact-discovery` dictionary rate limiter with Redis bounds.

### Long term (the roadmap)
Establish the `ai_assist` Claude orchestration layer into active pipelines. Introduce UI visualization arrays displaying conversion metrics over historically tracked schedules. Scale scraper implementations bypassing traditional authwalls using residential proxy rotations.

---

## 13. Contributor Entry Points

### Good first issues (no prior codebase knowledge needed)
1. Add `total_count` pagination wrappers to `/api/jobs` (`aggregator-service/main.py`).
2. Add explicit file type upload restrictions mapping magic bytes (`email-generator-service/main.py`).
3. Correct `crawler-service/Dockerfile` to employ a non-root `appuser`.
4. Migrate `_domain_rate` in `verifier.py` to use `redis-py` standard implementations.
5. Abstract generic Jinja2 logic out of `/api/digest` into parameterized payloads.

### Intermediate issues (requires understanding one service)
1. Abstract Playwright context closures inside try/finally blocks preventing memory leaks (`contact-discovery-service/discovery.py`).
2. Implement specific Exception catchers replacing global Exception nets across scraper pipelines (`scraper-service/main.py`).
3. Connect the Unstop scraper metadata fully into Gateway proxy channels (`scraper-service/scrapers/unstop.py`).
4. Generate Pytest fixtures modeling Github API responses protecting CI environments (`tests/unit/`).
5. Rewrite Scheduler daemon scraping into direct HTTP POST requests invoking isolated worker routines (`scheduler/tasks.py`).

### Advanced issues (requires understanding the full pipeline)
1. Rewrite the composite orchestrator `POST /api/workflow/apply` discarding arbitrary sleep timers.
2. Integrate a basic OAuth or API Key authentication intercept middleware over the Gateway proxy map.
3. Expand asynchronous Playwright handling logic combating generic Cloudflare authwalls dynamically without requiring human intervention.

---

## 14. Appendix

### Environment variables — complete reference
| Variable | Service | Required | Default | Description |
|----------|---------|----------|---------|-------------|
| `DATABASE_URL` | Aggregator, Contact, Email | Yes | `postgresql://...` | Connection URI |
| `REDIS_HOST` | Aggregator, Crawler, Scraper | Yes | `redis` | Message broker host |
| `REDIS_PORT` | Aggregator, Crawler, Scraper | No | `6379` | Message broker port |
| `GITHUB_TOKEN` | Contact | No | `None` | Elevates GH API limits |
| `GMAIL_ADDRESS` | Email | Yes | `None` | Dispatch host |
| `GMAIL_APP_PASSWORD`| Email | Yes | `None` | SMTP validation |
| `YOUR_NAME` | Email | No | `Applicant`| Profile injection |
| `OLLAMA_BASE_URL` | Email | No | `http://host.docker.internal:11434` | Local LLM host |
| `CRAWL_INTERVAL_HOURS`| Scheduler | No | `8` | Operational loop interval |
| `SCRAPER_WAIT_SECS` | Scheduler | No | `60` | Post-scrape normalization buffer |
| `GATEWAY_PORT` | Gateway | No | `8080` | Public dashboard assignment |

### External services and APIs used
- **Clearbit Autocomplete API**: Public endpoint. No Auth. Free tier. Used for domain inference.
- **GitHub API**: Public `/search` and `/orgs` mapping. Elevated by optional `GITHUB_TOKEN`. Limits: 60/hr public, 5000/hr auth.
- **LinkedIn Public Directory**: Playwright rendered. Bounded heavily by bot-protection walls. 
- **Ollama**: Localhost API. Used for drafting templates. Zero external cost.
- **Gmail SMTP**: Authorized endpoints securely tracking external text submissions.

### Dependency audit
Dependencies are cleanly segregated into standard configurations inside `requirements.txt`.
- Outdated: No severely outdated distributions noted. `FastAPI` runs efficiently.
- Unused: None explicitly noted.
- Note: Run `pip install pip-audit && pip-audit` on each service container independently to capture true production vulnerability metrics.

---

## 15. Security Audit

### 15.1 Secrets & Credentials Management
- **Findings**: The core `docker-compose.yml` mounts sensitive strings directly inside environment configuration blocks (`POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-jobpass}`).
- **Exposure**: `.env.example` correctly masks literal values.
- **Hardcoded**: None found across the python modules directly. The services cleanly inherit environment tokens.

### 15.2 Input Validation & Injection
- **SQLi**: `asyncpg` operates strictly via parameterized arguments (`$1, $2`). The query compiler strictly avoids `.format()` or string concatenation injection vectors. Raw queries are secure. 
- **Path Traversal**: `email-generator-service/main.py:280` handles arbitrary file uploads. While the file isn't written to disk physically, it relies purely on `.endswith('.pdf')` rather than checking magic bytes.
- **XSS**: Scraped data relies on the frontend `dashboard.html` for sanitization. Depending on JS configuration, un-sanitized job titles could manipulate DOM structures.

### 15.3 Authentication & Authorization
- **Status**: Non-existent. 
- **Exposed Endpoints**: The Gateway (`:8080`) actively permits `DELETE /contacts`, `PATCH /jobs`, and `POST /emails/{id}/send` with zero authentication bounds. Anyone possessing the IP space can delete data or trigger outbound spam campaigns from the user's Gmail address.
- **Recommendation**: Deploying BasicAuth or API Header verification across the Gateway proxy is mandatory prior to cloud hosting.

### 15.4 Dependency Vulnerabilities
- Scan commands directly via:
  ```bash
  pip install pip-audit && pip-audit
  ```
- Packages like `FastAPI` and `httpx` maintain minimal surface area but should be systematically tracked in CI environments.

### 15.5 Scrapy & Playwright Security
- **Sandboxing**: Playwright actively initializes utilizing `--no-sandbox` to operate inside Docker arrays. This implies browser escape vulnerabilities fundamentally jeopardize the entire container runtime.
- **SSL**: Did not observe arbitrary `VERIFY_SSL = False` conditions, meaning internal proxy MITM architectures remain mitigated.

### 15.6 SMTP & Email Security
- **Connection**: `smtplib.SMTP_SSL` securely wraps outbound data packets.
- **Spoofing**: Outbound headers map precisely to the initialized `GMAIL_ADDRESS`. Header injection vectors remain low due to Python standard library `EmailMessage` abstractions sanitizing parameter data.

### 15.7 Docker & Infrastructure Security
- **Root Operations**: `crawler-service` utilizes the default root operator traversing its internal operations.
- **Exposed Ports**: `docker-compose.yml` maliciously exposes `5433` (Postgres) and `6379` (Redis) broadly to the `0.0.0.0` host rather than strictly containing routing to the isolated `jobnet` bridge layer.

### 15.8 Data Privacy
- **Retention**: Discovered PII (Names, Emails) strictly maintain permanence in Postgres with zero purging lifecycle attached.
- **SBERT Cache**: Resumes are parsed instantly but not explicitly stored or encrypted at rest on the database.

### 15.9 Security Summary Table

| # | Finding | Severity | File/Location | Fix Effort |
|---|---------|----------|---------------|------------|
| 1 | Lack of Auth on Gateway | CRITICAL | `gateway/main.py` | 1 hour |
| 2 | Exposed Postgres/Redis host ports | HIGH | `docker-compose.yml` | 10 mins |
| 3 | Crawler executing as root | HIGH | `crawler-service/Dockerfile` | 10 mins |
| 4 | File upload bypass potential | MEDIUM | `email-generator-service/main.py` | 2 hours |
| 5 | Unpurged PII databases | LOW | `contact-discovery-service` | 1 hour |

### 15.10 Security Hardening Roadmap

**Do immediately (before exposing this on any public network)**
1. Strip `- "5433:5432"` and `- "6379:6379"` from `docker-compose.yml`.
2. Append `Depends` authentication routines mapping a generic API Key onto `gateway/main.py`.

**Do before v1.0**
1. Implement a unified `appuser` enforcement standard universally across Docker architectures.
2. Abstract File uploads to validate true magic byte assignments.

**Industry standard hardening (longer term)**
```bash
# Run SAST and secret validation checks automatically
bandit -r . 
trivy image jobhunter_scraper
semgrep --config=auto
detect-secrets scan
```
Add OAuth logic mapping distinct dashboard control configurations safely over standard JWT bearer paradigms.
