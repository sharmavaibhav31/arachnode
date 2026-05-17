# GUIDE — Job Discovery System: Start, Run & Use

> **Everything runs through Docker Compose. You need Docker Desktop (or Docker Engine + Compose plugin) and nothing else.**

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Engine | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Docker Compose | v2 | bundled with Docker Desktop |

Verify:
```bash
docker --version        # Docker version 24.x.x
docker compose version  # Docker Compose version v2.x.x
```

---

## Step 1 — Configure environment

```bash
cd /home/vaibhav-sharma/Projects/Job_crawler/jobCrawler
cp .env.example .env   # if the file doesn't exist, create it manually (see below)
```

Minimum required `.env` (copy-paste and fill in real values):

```dotenv
# ── PostgreSQL ──────────────────────────────────
POSTGRES_USER=jobuser
POSTGRES_PASSWORD=jobpass
POSTGRES_DB=jobsdb

# ── What you are looking for ────────────────────
JOBSEEKER_ROLE=Backend Engineer
JOBSEEKER_STACK=Python,FastAPI,PostgreSQL,Redis,Go

# ── Email sending (optional — skip if you don't need to send emails) ──
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   # 16-char Gmail App Password

# ── Email template personalisation ──────────────
YOUR_NAME=Your Full Name
YOUR_GITHUB_URL=https://github.com/yourusername

# ── Ollama (optional — for AI-personalised emails) ──
# Leave as-is if Ollama is running locally; delete if not using it
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

> **`GMAIL_APP_PASSWORD`** — Go to [Google Account → Security → App Passwords](https://myaccount.google.com/apppasswords), create a new app password for "Mail", and paste the 16-char code.

---

## Step 2 — Start the full stack

```bash
docker compose up --build
```

This starts **8 services** in the correct order automatically:

```
redis + postgres
    ↓
aggregator + scraper + contact-discovery + email-generator
    ↓
gateway (serves dashboard at :8080)
    ↓
scheduler (starts automated pipeline)
```

First build takes 3–5 minutes (downloading base images + installing Python deps).  
Subsequent starts: `docker compose up` (no `--build`) — under 30 seconds.

---

## Reset local development state

Use the scoped reset helper when you want a clean local development run without
destroying Docker volumes or unrelated Redis data:

```bash
make reset
```

The script prompts for confirmation, then:

- stops app services while keeping Postgres and Redis available
- truncates local Arachnode tables if present: `emails`, `contacts`, `jobs`
- deletes Arachnode Redis state: `jobs:raw`, `dedup:*`, `dedup:agg:*`
- clears the scheduler run summary file when the shared data volume is mounted
- restarts the Docker Compose stack by default

Useful variants:

```bash
./scripts/reset.sh --yes
./scripts/reset.sh --no-restart
```

With `--no-restart`, the database and Redis reset still run, but the shared
scheduler summary file is left untouched because the gateway/scheduler
containers are not restarted.

---

## Step 3 — Open the dashboard

Once you see this log line:

```
gateway  | INFO:     Application startup complete.
```

Open your browser:

```
http://localhost:8080
```

---

## Step 4 — Get your first jobs

The scheduler automatically triggers a scrape 60 seconds after startup.  
To trigger one immediately:

**Option A — Dashboard (recommended)**

1. Click **"▶ Trigger Scrape"** in the top-right navbar
2. Confirm role and stack → click **"Start Scraping"**
3. Wait ~60 seconds → click **"Refresh"** in the Jobs tab

**Option B — curl**

```bash
curl -X POST http://localhost:8080/api/scrape \
     -H "Content-Type: application/json" \
     -d '{"role": "Backend Engineer", "stack": ["Python", "Go", "FastAPI"]}'
```

**Option C — Run the Scrapy crawler manually**

```bash
docker compose exec scraper python -m scrapy crawl remotive
```

---

## Step 5 — The full workflow (dashboard walkthrough)

### 5.1 Jobs tab
- Cards appear automatically as jobs are scraped
- Filter by role, stack, or status using the filter bar
- **Left border colour** = status: amber = new, green = applied, red = ignored
- Hover a card to reveal three action buttons:
  - 👤 **Discover** — finds contacts at that company (runs in background)
  - ✉ **Draft** — generates a cold email via AI/template
  - ✓ **Apply** — marks the job as applied
- **Click a card** → detail panel slides in from the right, showing contacts + existing emails

### 5.2 Contacts tab
- Shows all contacts discovered by the pipeline
- Filter by company using the search box
- Click a row to expand and see the discovery source + copy-email button
- Click column headers to sort

### 5.3 Emails tab
- Shows all generated email drafts
- 👁 Click **View** to read the full email inline
- 📤 Click **Send** to send via Gmail (requires `GMAIL_APP_PASSWORD` in `.env`)

### 5.4 Stats tab
- Key metrics: total jobs, applied, contacts found, emails drafted
- Bar chart: jobs by source
- **Last Pipeline Run** — shows when the scheduler last ran and how many items it processed

---

## Useful commands

```bash
# View logs for a specific service
docker compose logs -f gateway
docker compose logs -f scheduler
docker compose logs -f aggregator

# Check if all services are healthy
curl http://localhost:8080/api/health | python3 -m json.tool

# View the latest scheduler run summary
curl http://localhost:8080/api/summary | python3 -m json.tool

# Stop everything (data is preserved in Docker volumes)
docker compose stop

# Stop and delete all data (full reset)
docker compose down -v

# Restart a single service after a code change
docker compose up --build gateway
```

---

## Run the scheduler manually (without waiting for the cron)

```bash
# Trigger just the scrape cycle right now
docker compose run --rm -e MANUAL_TASK=scrape scheduler

# Trigger just the contact discovery cycle
docker compose run --rm -e MANUAL_TASK=discover scheduler

# Trigger just email draft pre-generation
docker compose run --rm -e MANUAL_TASK=draft scheduler

# Run all three in sequence
docker compose run --rm -e MANUAL_TASK=all scheduler
```

---

## Automated schedule (default)

| Cycle | Interval | What happens |
|---|---|---|
| **Scrape** | Every 8h (starts immediately) | Scrapes Naukri, LinkedIn, Internshala + runs Scrapy spiders |
| **Discover** | Every 24h (+4h offset) | Finds contacts for up to 20 new jobs |
| **Draft** | Every 24h (+8h offset) | Pre-generates cold outreach emails for jobs with contacts |

Change intervals without rebuilding:

```bash
# In .env
CRAWL_INTERVAL_HOURS=4
DISCOVER_INTERVAL_HOURS=12
```

Then restart only the scheduler: `docker compose restart scheduler`

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard shows "Cannot reach backend" | Run `docker compose ps` — check gateway is Up and Healthy |
| Jobs tab is empty after scrape | Check `docker compose logs scraper` for HTTP errors; platforms may block headless requests |
| Emails fail to send | Verify `GMAIL_APP_PASSWORD` in `.env`; must be an App Password, not your account password |
| Ollama errors in email-gen logs | Ollama is optional — emails still generate from static templates (`fallbacks.yaml`) |
| Postgres connection refused | Give it 10–15 seconds on first start; healthchecks handle the ordering |
| Port 8080 already in use | Set `GATEWAY_PORT=9090` in `.env` and open `http://localhost:9090` |

---

## Direct API access (no dashboard)

All endpoints are available at `http://localhost:8080/api/` — interactive docs at:

```
http://localhost:8080/api/docs
```

