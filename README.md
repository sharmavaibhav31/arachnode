# Arachnode

A self-hosted microservice application for tracking automated job discovery, contact enrichment, and cold email generation.

`Python 3.11` `FastAPI` `Scrapy` `Docker`

I built this because managing engineering applications at product-based startups manually was slow and unscalable. As a third-year student approaching placement season, I needed a way to find relevant roles across multiple scattered platforms, uncover who the actual hiring managers were, and draft personalized outreach emails without spending hours on repetitive clicking. This system automates the top of the job-hunt funnel so I can focus on interviewing.

## Demo placeholder
https://arachnode.vercel.app/  
(https://youtu.be/GiibnmC7kiY)

The dashboard provides a unified view of the entire pipeline. It displays active job listings filtered by status and tech stack on the main screen, a tabular view of all discovered contacts with their verification status, and an email generation pane where draft outreach templates are queued. Four key metrics track total jobs, applied jobs, discovered contacts, and drafted emails at the top.

## Features

### Job discovery
- Crawls tech-focused directories (Wellfound, YC Jobs, Remotive) using Scrapy.
- Scrapes structured job platforms (Naukri, LinkedIn, Internshala) via Playwright browser automation.
- Normalizes job events and aggregates them into a central PostgreSQL database.
- Deduplicates identical job postings intelligently based on company and role.

### Outreach automation
- Queries the GitHub API and uses OSINT techniques to find technical stakeholders and recruiters for specific companies.
- Validates discovered email addresses via SMTP checks.
- Generates context-aware cold emails using locally hosted LLM models (Ollama/Mistral) and Jinja2 templates.
- Enqueues draft outbound emails for manual review and Gmail sending.

### Tracking & dashboard
- Proxies all backend services through a unified API gateway.
- Visualizes job funnel metrics via an interactive, single-page HTML dashboard.
- Maintains atomic state tracking for each job application (new, applied, ignored).
- Runs the entire discovery-to-draft pipeline in the background using APScheduler cron jobs.

## Architecture

The system uses an event-driven microservice architecture with Python across the stack. I chose Redis Streams over a heavier broker like Kafka because it provides sufficient consumer group semantics with minimal operational overhead for a self-hosted personal tool. The loosely coupled services allow background crawling and contact discovery to scale and fail independently without blocking the API gateway or the web dashboard.

```text
                                                  ┌────────────────────────┐
┌─────────────────────┐    Jobs via REST POST     │                        │
│                     ├──────────────────────────►│    Gateway Service     │
│  Scheduler Service  │                           │        (:8080)         │
│    (APScheduler)    │    Trigger operations     │                        │
└──────────┬──────────┘                           └──────┬────────┬────────┘
           │                                             │        │
           │ Trigger spiders via POST               REST │        │ REST
           │                                             │        │
┌──────────▼──────────┐                           ┌──────▼────────▼────────┐
│                     │       Jobs via POST       │                        │
│  Platform Scraper   ├──────────────────────────►│   Aggregator Service   │
│      (:8001)        │                           │        (:8000)         │
└─────────────────────┘                           └──────┬─────────────────┘
                                                         │        ▲
┌─────────────────────┐       Jobs via Stream            │        │ Store
│                     │                           ┌──────▼────────▼────────┐
│   Crawler Service   ├───────[ Redis ]──────────►│      PostgreSQL        │
│   (Scrapy spider)   │         Stream            │      Database DB       │
└─────────────────────┘                           └──────┬────────┬────────┘
                                                         │        │
┌─────────────────────┐                           ┌──────▼────────▼────────┐
│                     │   Trigger via REST POST   │                        │
│    Email Service    ◄───────────────────────────┤   Contact Discovery    │
│       (:8003)       │                           │        (:8002)         │
└─────────────────────┘                           └────────────────────────┘
```

| Service | Language/Framework | Port | Responsibility |
| --- | --- | --- | --- |
| Crawler | Python / Scrapy | None | Navigates startup directories, extracts job listings, and publishes items to a Redis stream. |
| Platform Scraper | Python / FastAPI / Playwright | 8001 | Handles on-demand JavaScript-heavy browser scraping for platforms like LinkedIn. |
| Aggregator | Python / FastAPI / asyncpg | 8000 | Consumes the Redis stream, deduplicates entries, saves to Postgres, and serves job queries. |
| Contact Discovery | Python / FastAPI / httpx | 8002 | Uses OSINT and GitHub APIs to uncover potential recruiter/manager emails per company. |
| Email Generator | Python / FastAPI / Ollama | 8003 | Renders Jinja2 templates and interfaces with Ollama to draft contextual cold emails. |
| Gateway | Python / FastAPI / Vanilla JS | 8080 | Proxies frontend requests, composes complex workflows, and serves the static dashboard. |
| Scheduler | Python / APScheduler | None | Periodically triggers crawlers, contact discovery, and automated email drafting. |

## Tech stack

| Technology | Purpose |
| --- | --- |
| FastAPI | Handles all internal REST APIs and the unified Gateway proxy logic. |
| Scrapy | Crawls structured and unstructured startup directories with high concurrency. |
| Playwright | Renders JavaScript-heavy career pages (LinkedIn, Wellfound, Naukri). |
| asyncpg | Provides direct async connections to PostgreSQL for high-performance writes. |
| Redis Streams | Acts as a lightweight event broker decoupling crawling from persistence. |
| PostgreSQL | Stores unified job listings, contact profiles, and email drafts. |
| APScheduler | Manages chronologically scheduled automation cycles in a background process. |
| Jinja2 | Populates string templates for standard cold email structures. |
| Ollama | Drafts highly customized outreach emails locally using open-weights reasoning LLMs. |
| httpx | Performs asynchronous outbound API calls to GitHub and other OSINT sources. |
| BeautifulSoup4 | Parses static HTML response blobs extracting email patterns and target links. |
| smtplib | Validates discovered email domains and sends approved outreach via Gmail SMTP. |
| Docker | Containerizes services for isolated execution environments. |
| docker-compose | Orchestrates the multi-container stack, network routing, and volumes. |
| Chart.js | Renders job metrics and funnel conversion graphs on the dashboard. |
| pytest | Executes unit, integration, and end-to-end tests across the monorepo. |
| testcontainers | Spins up ephemeral Postgres and Redis instances automatically for integration testing. |

## Getting started

### Prerequisites

- [ ] Python 3.11+
- [ ] Docker 24+ and docker-compose v2
- [ ] Redis 7 (or run via Docker)
- [ ] Ollama (optional, for AI-enhanced emails)
- [ ] A Gmail account with an App Password (for sending emails)

Note: If you do not install Ollama, the email generator gracefully degrades to standard parameterized Jinja2 templates. Focus is maintained on contact discovery and job aggregation.

### Installation

1. Clone the repository and navigate into the root directory.
```bash
git clone https://github.com/sharmavaibhav31/arachnode.git
cd arachnode
```

2. Copy the example environment file and fill in the required variables.
```bash
cp .env.example .env
```

3. Install the Playwright chromium browser locally if you plan to aggressively run or test the crawler outside docker.
```bash
playwright install chromium
```

4. Bring up the full infrastructure stack via docker-compose.
```bash
docker compose up --build -d
```

Visit `http://localhost:8080` to open the dashboard.

### Resetting local development state

When local data gets stale during development, reset only Arachnode-owned
Postgres and Redis state with:

```bash
make reset
```

or directly:

```bash
./scripts/reset.sh
```

The reset command asks for confirmation before changing anything. It truncates
the local `emails`, `contacts`, and `jobs` tables if they exist, deletes the
`jobs:raw` Redis stream, and removes Arachnode dedup keys matching `dedup:*`
and `dedup:agg:*`. It does not remove Docker volumes and does not run Redis
`FLUSHALL`, so unrelated local Redis data is left alone.

For non-interactive local use:

```bash
./scripts/reset.sh --yes
```

To reset state without restarting the full Docker stack:

```bash
./scripts/reset.sh --no-restart
```

With `--no-restart`, the database and Redis reset still run, but the shared
scheduler summary file is left untouched because the gateway/scheduler
containers are not restarted.

### Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| **Core** | | | |
| `POSTGRES_USER` | Yes | `jobuser` | Target username for the PostgreSQL database container. |
| `POSTGRES_PASSWORD` | Yes | `jobpass` | Target password for the PostgreSQL database container. |
| `POSTGRES_DB` | Yes | `jobsdb` | Target database schema name inside PostgreSQL. |
| `GATEWAY_PORT` | No | `8080` | External routing port exposed on localhost for the UI and Gateway. |
| **Crawler** | | | |
| `JOBSEEKER_ROLE` | No | `Backend Engineer` | The primary job role targeted during scraped searches. |
| `JOBSEEKER_STACK` | No | `Python,FastAPI` | Target developer tools used to filter matching jobs. |
| **Email** | | | |
| `GMAIL_ADDRESS` | No | | Senders email used for outbound applications. |
| `GMAIL_APP_PASSWORD` | No | | Secure remote app password to authorize `smtplib`. |
| `YOUR_NAME` | No | `Applicant` | Outbound sender name attached to drafted cold emails. |
| `YOUR_GITHUB_URL` | No | | Included in footer context for recruiter outreach prompts. |
| **Ollama** | | | |
| `OLLAMA_BASE_URL` | No | `http://host.docker.internal:11434` | Gateway path to resolve localhost Ollama APIs inside container bridges. |

## Usage

### Running a manual scrape

Trigger an intense, immediate scrape against configured structured target platforms via the gateway proxy.

```bash
curl -X POST http://localhost:8080/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"role": "Backend Engineer", "platforms": ["internshala"]}'
```

This request kicks off a Playwright-based crawling procedure in the scraper service. Jobs retrieved from this flow bypass Redis and directly hit the aggregator via POST callbacks for synchronous feedback loops.

### The apply workflow

Execute the entire discovery-to-email funnel for an individual existing job ID in your database. 

```bash
curl -X POST http://localhost:8080/api/workflow/apply \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "aa1f4bc0-5c08-4531-9c8a-721fb1afe033",
    "template": "cold_outreach",
    "roles": ["Engineering Manager", "Technical Recruiter"]
  }'
```

Example JSON response:
```json
{
  "job": {
    "id": "aa1f4bc0-5c08-4531-9c8a-721fb1afe033",
    "company": "Supabase",
    "role": "Postgres Engineer",
    "status": "new"
  },
  "contacts": [
    {
      "id": "b22f4bc0...",
      "name": "Jane Doe",
      "email": "jane@supabase.com",
      "verified": "verified"
    }
  ],
  "draft_email": {
    "id": "c33f4bc0...",
    "subject": "Backend Engineer application — Supabase",
    "body": "Hi Jane,\n\nI was browsing open roles...",
    "status": "draft"
  }
}
```

### Automated scheduling

The APScheduler mechanism triggers unattended sweeps continually without manual user execution. Scrapes execute every 8 hours, loading raw lists into the database. Every 24 hours (offset by 4 hours to avoid deadlock throttling), the contact discovery worker fetches all unprocessed generic companies and scours GitHub/OSINT APIs for recruiter points of contact. Finally, a draft execution process constructs customized outgoing email strings based on the recently located verified addresses, leaving them prepared in the UI dashboard.

## Project structure

```text
├── aggregator-service/          # Persists scraped data; serves jobs REST API
│   ├── main.py                  # FastAPI route declarations
│   ├── db.py                    # asyncpg query interfaces
│   ├── consumer.py              # Background Redis pub-sub listener
│   └── Dockerfile
├── contact-discovery-service/   # Performs OSINT queries discovering employees
│   ├── main.py                  # Traces company names to Github API endpoints
│   ├── storage.py               # Local sync Postgres queries for caching contacts
│   ├── verifier.py              # Connects to domains tracking SMTP responses
│   └── Dockerfile               
├── crawler-service/             # Emits background job entities into Redis stream
│   ├── crawler/spiders/         # Target pipeline targets (yc.py, remotive.py)
│   ├── scrapy.cfg               # Base application scrapy configuration definition
│   └── Dockerfile
├── email-generator-service/     # Local LLM drafting integrations
│   ├── main.py
│   ├── ollama_client.py         # Interfaces locally configured Mistral
│   ├── templates/               # Contains structured Jinja2 text templates
│   └── Dockerfile
├── gateway/                     # Application proxy endpoints and user interface
│   ├── main.py                  # API fanout routers linking isolated tasks
│   ├── proxy.py                 # httpx abstractions executing proxy mappings
│   ├── dashboard.html           # Single-page vanilla JS UI tracking state
│   └── Dockerfile
├── scheduler/                   # Centralized task execution interval timers
│   ├── main.py                  
│   ├── tasks.py                 # Wraps Gateway APIs in timed interval routines
│   ├── logger.py                # Intercepts log formats translating properties to JSON
│   └── Dockerfile
├── docker-compose.yml           # Core network mapping execution environments
└── README.md
```

## Development

### Running a single service locally (without Docker)

If modifying specific logical rules on a proxy or contact crawler, you can run isolated services independently using virtual environments.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
cd crawler-service
pip install -r requirements.txt
export REDIS_HOST=localhost
export JOBSEEKER_ROLE="Backend Engineer"
scrapy crawl remotive
```

### Running tests

Execute distinct testing levels using `pytest`.

```bash
pytest tests/unit
```
Executes independent business logic checks against mock objects predicting localized function output expectations.

```bash
pytest tests/integration
```
Validates local inter-service message bus streams utilizing `testcontainers` initializing raw Postgres and Redis nodes specifically for testing workflows.

```bash
pytest tests/contracts
```
Asserts schema integrity among disjoint services expecting uniform HTTP data body formats.

```bash
pytest tests/e2e
```
Fires browser-based integration actions traversing full API endpoints across unified proxy configurations simulating typical dashboard flows.

### Adding a new spider

1. Navigate to `crawler-service/crawler/spiders/`.
2. Produce a class extending `scrapy.Spider` providing specific domain configurations.
3. Configure target parse endpoints locating structured text data blobs in HTML.
4. Yield Python dictionary structures fitting the common normalization pipeline.

```python
import scrapy

class NewStartupSpider(scrapy.Spider):
    name = 'new_startup'
    start_urls = ['https://newstartupdomain.com/jobs']

    def parse(self, response):
        for job in response.css('.job-posting'):
            yield {
                'company': job.css('.co-name::text').get(),
                'role': job.css('.title::text').get(),
                'url': response.urljoin(job.css('a::attr(href)').get()),
            }
```

### Adding a new job platform

1. Within `scraper-service/scripts`, attach a new class utilizing the abstract BaseScraper.
2. Structure internal `Playwright` navigation commands targeting complex JavaScript forms.
3. Append mapping identifiers onto the primary `/api/scrape` incoming interface.

## API reference

Endpoints presented represent Gateway proxy targets. Internal traffic targets utilize disparate routing identifiers unavailable publicly.

#### GET /api/jobs
Returns tracked job listings from aggregator database instances.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| `role` | str | `None` | Case-insensitive substring match checking indexed job role titles. |
| `stack` | str | `None` | Comma-separated array enforcing matching stack requirements on fetched rows. |
| `status` | str | `None` | Filter responses identifying specific targets: `new`, `applied`, `ignored`. |
| `sort` | str | `latest` | Returns values respecting chronological database ingestion timing. |
| `limit` | int | `50` | Row cap filtering results. Max `500`. |

```bash
curl -X GET "http://localhost:8080/api/jobs?status=new&limit=2"
```

```json
[
  {
    "id": "c1f7a0...",
    "company": "Example Startup",
    "role": "Backend Engineer",
    "status": "new",
    "posted_at": "2026-04-03T20:21:00"
  },
  ...
]
```

#### GET /api/stats
Returns generic system metadata metric summaries assessing target health operations.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| N/A | N/A | N/A | Receives no query formatting overrides. |

```bash
curl -X GET "http://localhost:8080/api/stats"
```

```json
{
  "total_jobs": 124,
  "sources": {"ycombinator": 80, "remotive": 44},
  "statuses": {"new": 100, "applied": 24, "ignored": 0}
}
```

#### POST /api/scrape
Forces scraper pipeline executing synchronous retrieval bypassing Redis structures.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| (Body) | JSON | `Required` | Defines query `platforms`, `role`, and string based `stack` elements driving results. |

```bash
curl -X POST "http://localhost:8080/api/scrape" \
  -H "Content-Type: application/json" \
  -d '{"role": "Backend Engineer", "platforms": ["naukri"]}'
```

```json
{
  "status": "success",
  "scraped": 15,
  "inserted": 5,
  "duplicates": 10
}
```

#### GET /api/contacts
Retrieves discovered employee contacts from target corporate database structures.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| `company` | str | `None` | Enforces specific string matching searching target corporation names. |

```bash
curl -X GET "http://localhost:8080/api/contacts?company=Supabase"
```

```json
[
  {
    "id": "e331bc...",
    "name": "Jane Doe",
    "company": "Supabase",
    "role": "Recruiter",
    "email": "jane@supabase.com",
    "verified": "verified"
  },
  ...
]
```

#### POST /api/discover
Synchronously initiates a Github / OSINT tracking request discovering potential contacts related to a corporate target.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| (Body) | JSON | `Required` | Supplies target `company` title and optional internal role identification filtering arrays. |

```bash
curl -X POST "http://localhost:8080/api/discover" \
  -H "Content-Type: application/json" \
  -d '{"company": "Supabase"}'
```

```json
{
  "status": "success",
  "found": 2,
  "details": "Triggered asynchronous ingestion process assessing 2 generic profile identifiers."
}
```

#### GET /api/emails
Extracts formatted text outbound applications produced by locally hosted LLMs.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| `job_id` | str | `None` | Returns emails specific to exact database application roles. |

```bash
curl -X GET "http://localhost:8080/api/emails?job_id=aa1f4bc0-5c08-4531-9c8a-721fb1afe033"
```

```json
[
  {
    "id": "a90bb...",
    "subject": "Backend Engineer role — Supabase",
    "status": "draft",
    "generated_at": "2026-04-03T21:14:00"
  },
  ...
]
```

#### POST /api/generate
Processes target templates into rendered string blobs utilizing configured LLM hosts or Jinja2 defaults.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| (Body) | JSON | `Required` | Targets `job_id`, `contact_id`, and `template` properties configuring response rendering inputs. |

```bash
curl -X POST "http://localhost:8080/api/generate" \
  -H "Content-Type: application/json" \
  -d '{"job_id": "aa1f4bc0...", "template": "followup"}'
```

```json
{
  "email_id": "b1aa2...",
  "subject": "Checking in on my backend application",
  "body": "Hi Jane,\n\nFollowing up on my previous message...",
  "status": "draft"
}
```

#### POST /api/workflow/apply
Comprehensively triggers cross-domain discovery and text drafting across proxy channels producing singular composite outputs.

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| (Body) | JSON | `Required` | Supples exact `job_id` properties ensuring precise target workflow execution properties. |

```bash
curl -X POST "http://localhost:8080/api/workflow/apply" \
  -H "Content-Type: application/json" \
  -d '{"job_id": "aa1f4bc0..."}'
```

```json
{
  "job": {
    "id": "aa1f4bc0...",
    "company": "Supabase"
  },
  "contacts": [...],
  "draft_email": {...}
}
```

## Roadmap

Built:
- [x] Web crawler (Wellfound, YC, Remotive)
- [x] Platform scraper (Naukri, LinkedIn, Internshala)
- [x] Job aggregation with deduplication
- [x] Contact discovery via OSINT
- [x] Cold email generation (Jinja2 + Ollama)
- [x] API gateway with dashboard
- [x] Automated scheduling

Planned:
- [ ] Add resume parsing module adapting outbound email drafting according to distinct required keywords mapped off CV text profiles.
- [ ] Incorporate asynchronous outgoing SMTP workflows validating automated delivery logic bypassing local Gmail browser access steps.
- [ ] Construct generic containerized application form completion agents accessing target URLs executing headless submission steps via LLM mapping properties.
- [ ] Extend dashboard layout capturing historical metric trend data visualizations scaling historical outreach efforts correctly.
- [ ] Refactor internal Redis Streams implementation allowing scalable distributed cluster operation instances scaling processing concurrency properly.

## Ethics & responsible use

This tool operates exclusively on publicly accessible HTML structures parsing standardized data points mimicking common browser indexing mechanisms. I strictly adhere to site-wide `robots.txt` properties and rate limit execution timing enforcing respect for operational bandwidth limitations on target directories. Additionally, discovering organizational points of contact serves purely targeted professional outreach efforts mitigating automated bulk spam logic loops by mandating manual user verification checks traversing final outbound gateway executions.

## Contributing

While I designed this application managing my personal placement operations efficiently, contributions proposing intelligent scaling structures remain absolutely welcome. Incorporating supplemental crawler targets, parsing extensions spanning newly structured job platforms, or generating flexible Jinja2 text templates all provide significant collaborative value. 

File specific bug tickets or propose standardized PR adjustments traversing the typical GitHub operational flow referencing unified repository structures clearly.

## License

MIT © Vaibhav Sharma 2026

*Note: The MIT license covers the tool's source code architecture completely. Users remain independently responsible guiding localized deployment targets ensuring ethical compliance adhering to scraped platform data handling regulations safely.*
