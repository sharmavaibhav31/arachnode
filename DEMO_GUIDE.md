# JobHunter Demo Guide

## Starting the System (3 Commands)

```bash
# 1. Set up your environment
cp .env.example .env
# Edit .env — at minimum set JOBHUNTER_API_KEY and your Gmail credentials

# 2. Start everything
docker compose up -d --build

# 3. Validate all services are healthy
bash scripts/validate.sh
```

Open the dashboard: **http://localhost:8080**

---

## Setting Your API Key

1. Open http://localhost:8080
2. Click the **⚙ Settings** button in the top-right navbar
3. Enter the value of `JOBHUNTER_API_KEY` from your `.env` file
4. Click **Save** — the key is stored in your browser's `localStorage`

If you skip this, all API calls will return `401 Unauthorized`.

---

## 10-Minute Scripted Demo Flow

### Minute 0–1: System Overview
- Open http://localhost:8080
- Point out the **service health bar** in the navbar — green dots = all systems up
- Explain: "This is a fully self-hosted job discovery system. No third-party SaaS, no recurring fees."

### Minute 1–2: Jobs Dashboard
- Click **Jobs** tab — show the paginated job grid
- Demonstrate **filters**: role keyword search, stack filter (e.g. "Python"), status filter
- Show the **Load More** button at the bottom (pagination is live)
- Click a job card to open the **detail panel** on the right

### Minute 2–3: Job Status Workflow
- In the detail panel, change a job status from **New → Applied**
- The card updates instantly — "Status is synced to the database immediately"

### Minute 3–4: Contact Discovery
- Click **Contacts** tab
- Show the contacts table — explain: "These were discovered automatically by the scheduler"
- Search for a company name — show real-time filtering via the GIN trigram index

### Minute 4–5: Manual Discovery Trigger
- Go back to a job detail panel
- Click **Run Workflow** button
- Say: *"This triggers contact discovery in the background. The system polls for up to 20 seconds, then generates a draft email immediately — even if discovery is still running."*
- Show the draft email that appears in the panel

### Minute 5–6: Email Generator
- Click **Emails** tab (or the draft link in the job panel)
- Show the generated cold email — subject line, personalised body
- Switch template: "We have four templates: cold outreach, recruiter outreach, referral, follow-up"
- Click **Send** to send via Gmail SMTP (live demo if credentials are set)

### Minute 6–7: Scheduler & Automation
- Click **Summary** tab or the run summary card on the dashboard
- Show `run_summary.json` data: jobs discovered, contacts found, emails drafted
- Say: *"The scheduler runs autonomously every 8 hours. No manual intervention needed."*

### Minute 7–8: Weekly Digest
- Explain: *"Every Sunday, the system emails you a digest of the week's new jobs — grouped by company, sorted by relevance to your stack."*
- Show the digest template in `email-generator-service/templates/`

### Minute 8–9: Security & Production Readiness
- Point to the API key in Settings — "All API calls require this key"
- Mention: database and Redis are on an internal Docker network — not accessible from outside
- Show `scripts/validate.sh` output — "One command to verify the entire system"

### Minute 9–10: Q&A Buffer
- Have `docker compose logs --tail=20 scheduler` ready to show live log output
- Have `docker compose ps` ready to show all services healthy

---

## What to Say When Something Takes Time

| Situation | What to say |
|-----------|-------------|
| Playwright browser launching | *"Playwright is spinning up a headless browser — this is a one-time startup cost per container."* |
| Ollama LLM call | *"Ollama is running the language model locally on your machine — no API costs, fully private. First call takes ~10s to load the model."* |
| Contact discovery pending | *"Discovery runs in the background — LinkedIn and GitHub rate-limit scraping requests, so we space them out. Check back in a minute."* |
| Spider taking time | *"The Scrapy spiders are crawling live job boards. Remotive and YC Jobs are fast; Glassdoor uses a headless browser so it takes ~30s."* |
| Build taking time | *"Docker is downloading Playwright's Chromium binary — ~170MB, one-time download."* |

---

## Known Limitations (Mention Proactively)

1. **Ollama is optional** — without it, email templates use YAML fallbacks. The emails are still good, just not LLM-personalised.

2. **LinkedIn discovery is rate-limited** — the system has Redis-backed rate limiting (3 SMTP checks/domain/hour). On the first run, you'll see "unverified" contacts until the system warms up.

3. **Glassdoor requires Playwright** — if the scraper container doesn't have Chromium available, the Glassdoor spider silently skips. The other 4 spiders (Remotive, YC Jobs, Wellfound, Cutshort) are pure HTTP and always work.

4. **No multi-user support** — this is a personal tool. The API key is shared and there's no user account system. Fine for personal use or single-user demos.

5. **Weekly digest requires Gmail** — SMTP credentials must be set. Without them, the digest is generated but not sent (stored as `draft` in the database).

---

## Useful Commands

```bash
# View live logs from any service
docker compose logs -f scheduler
docker compose logs -f contact
docker compose logs -f gateway

# Restart a single service without rebuilding
docker compose restart contact

# Rebuild and restart one service
docker compose up -d --build contact

# Access the database directly
docker exec -it $(docker compose ps -q postgres) psql -U jobuser jobsdb

# Access Redis directly
docker exec -it $(docker compose ps -q redis) redis-cli

# Run validation check
bash scripts/validate.sh

# Full teardown (preserves data volumes)
docker compose down

# Full teardown including data (DESTRUCTIVE)
docker compose down -v
```
