# API Gateway & Dashboard

The API Gateway proxies backend services behind a single port and serves a vanilla-JS dashboard at `GET /`.

```
Browser / curl
     │
     ▼
 Gateway :8080
  ├── /api/jobs/*         → aggregator:8000
  ├── /api/scrape         → scraper:8001
  ├── /api/contacts/*     → contact:8002
  ├── /api/emails/*       → email-gen:8003
  ├── /api/agent/search   → agent-search:8009
  ├── /api/agent/*        → gemini-agent:8010
  ├── /api/workflow/apply ← composite (orchestrated here)
  ├── /api/health         ← fans out to all services
  └── /                   ← dashboard.html
```

---

## Project layout

```
gateway/
├── main.py          # FastAPI gateway — routes + composite endpoint
├── proxy.py         # httpx helpers: generic forwarder + typed workflow helpers
├── dashboard.html   # Single-file vanilla JS dashboard
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Starting the full stack

### Prerequisites

```bash
# Copy env template and fill in your values
cp .env.example .env   # see variables listed in root README
```

### One command to launch everything

```bash
# From the repository root
docker compose up --build

# Then open the dashboard
open http://localhost:8080
```

### Service startup order (automatic via healthchecks)

```
redis + postgres  →  aggregator + scraper + contact + email-gen + agent-search + gemini-agent  →  gateway
```

The gateway will not start until backend services report healthy.

### Run the crawler (one-shot, separate command)

```bash
docker compose run --rm crawler scrapy crawl remotive
```

---

## Using the dashboard

### Typical workflow

1. **Open** `http://localhost:8080`
2. **Jobs tab** — click **▶ Run Scraper** to fetch fresh listings from Naukri, LinkedIn & Internshala. Jobs appear within ~30 s.
3. On any job card, click **👤 Discover** to find engineering contacts at that company (runs in background).
4. Click **✉ Draft** — the gateway calls `/api/workflow/apply`, which orchestrates job lookup → contact discovery → email generation in one request and opens a preview modal.
5. Click **Send** inside the modal to send the email via Gmail.
6. Switch to **🤖 Agent**, **Contacts**, **Emails**, and **Stats** tabs to chat with Gemini AI, run intent searches, and view pipeline results.

---

## API reference

Interactive docs: `http://localhost:8080/api/docs`

### `GET /api/health` — fan-out health check

```bash
curl http://localhost:8080/api/health
```
```json
{
  "gateway": "ok",
  "services": [
    {"service": "aggregator",   "status": "ok"},
    {"service": "scraper",      "status": "ok"},
    {"service": "contact",      "status": "ok"},
    {"service": "email-gen",    "status": "ok"},
    {"service": "agent-search", "status": "ok"},
    {"service": "gemini-agent", "status": "ok"},
    {"service": "crawler",      "status": "ok"}
  ]
}
```

### `POST /api/workflow/apply` — full apply workflow

```bash
curl -X POST http://localhost:8080/api/workflow/apply \
     -H "Content-Type: application/json" \
     -d '{"job_id": "<uuid>", "template": "cold_outreach"}'
```
```json
{
  "job":      { "id": "...", "company": "Razorpay", "role": "Backend Engineer", ... },
  "contacts": [{ "name": "Alice Smith", "email": "alice.smith@razorpay.com", ... }],
  "draft_email": { "email_id": "...", "subject": "...", "body": "..." }
}
```

### Proxy routes

| Gateway path | Upstream |
|---|---|
| `GET/POST /api/jobs` | aggregator `/jobs` |
| `GET/PATCH /api/jobs/{id}/status` | aggregator `/jobs/{id}/status` |
| `GET /api/stats` | aggregator `/stats` |
| `POST /api/scrape` | scraper `/scrape` |
| `POST /api/discover` | contact `/discover` |
| `GET /api/contacts` | contact `/contacts` |
| `DELETE /api/contacts/{id}` | contact `/contacts/{id}` |
| `POST /api/generate` | email-gen `/generate` |
| `GET /api/emails` | email-gen `/emails` |
| `PATCH /api/emails/{id}/status` | email-gen `/emails/{id}/status` |
| `POST /api/emails/{id}/send` | email-gen `/emails/{id}/send` |
| `POST /api/agent/search` | agent-search `/search` |
| `POST /api/agent/chat` | gemini-agent `/agent/chat` |
| `POST /api/agent/enhance-resume` | gemini-agent `/agent/enhance-resume` |
| `POST /api/agent/draft-email` | gemini-agent `/agent/draft-email` |

---

## Adding a new service behind the gateway

1. Add the service to `docker-compose.yml` on the `jobnet` network.
2. Add its base URL as an env var in `proxy.py` (e.g. `MY_SVC_URL`).
3. Add a proxy route in `main.py`:
   ```python
   @app.api_route("/api/my-service/{path:path}", methods=["GET","POST"])
   async def proxy_my_service(path: str, request: Request):
       return await proxy.proxy_request(request, f"{proxy.MY_SVC_URL}/{path}")
   ```
4. Rebuild the gateway container: `docker compose up --build gateway`

---

## Environment variables (root `.env`)

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `jobuser` | Database user |
| `POSTGRES_PASSWORD` | `jobpass` | Database password |
| `POSTGRES_DB` | `jobsdb` | Database name |
| `JOBHUNTER_API_KEY` | — | Gateway API authentication key (blank for dev mode) |
| `GEMINI_API_KEY` | — | Google Gemini API key for AI features |
| `JOBSEEKER_ROLE` | `Backend Engineer` | Crawler search role |
| `JOBSEEKER_STACK` | `Python,...` | Crawler stack filter |
| `GITHUB_TOKEN` | — | Contact discovery (optional, raises GH rate limit) |
| `GMAIL_ADDRESS` | — | Gmail sender address |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password |
| `YOUR_NAME` | `Applicant` | Used in email templates |
| `YOUR_GITHUB_URL` | — | Embedded in email templates |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama server for email gen |
| `GATEWAY_PORT` | `8080` | Host port for the gateway |
