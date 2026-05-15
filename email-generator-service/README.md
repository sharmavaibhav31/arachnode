# Cold Email Generator Service

A FastAPI microservice that drafts personalized cold emails for job applications using **Jinja2 templates** + an optional **local Ollama LLM** (mistral/llama3) for a one-line company product observation. Falls back to curated static observations from `fallbacks.yaml` when Ollama is unavailable.

---

## Project layout

```
email-generator-service/
├── main.py              # FastAPI app — all endpoints
├── generator.py         # Email generation pipeline (Ollama → fallback → Jinja2)
├── ollama_client.py     # Async Ollama REST client
├── mailer.py            # Gmail SMTP_SSL sender
├── storage.py           # asyncpg pool, emails table DDL, CRUD
├── fallbacks.yaml       # Static observations by domain (fintech, devtools…)
├── templates/
│   ├── cold_outreach.j2       # To hiring manager / engineer (≤150 words)
│   ├── recruiter_outreach.j2  # To recruiter (≤120 words)
│   ├── referral_outreach.j2   # To a mutual connection referral contact
│   └── followup.j2            # Follow-up after no reply (≤80 words)
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | asyncpg DSN (shared with aggregator / contact discovery) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama REST API base URL |
| `GMAIL_ADDRESS` | — | Your Gmail address for sending |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password (not login password) |
| `YOUR_NAME` | `Applicant` | Shown in email sign-off |
| `YOUR_GITHUB_URL` | — | GitHub profile URL embedded in emails |

---

## Ollama setup (optional but recommended)

Install Ollama, then pull the preferred model:

```bash
# Install (Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Pull models (mistral is preferred; llama3 is the fallback)
ollama pull mistral
ollama pull llama3   # optional

# Start the server (runs on http://localhost:11434 by default)
ollama serve
```

The service auto-detects which model is available. If Ollama is not running, it falls back to `fallbacks.yaml` silently — **no configuration change needed**.

---

## Quick start

### Local dev

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

### Docker

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

---

## Gmail App Password setup

1. Go to <https://myaccount.google.com/apppasswords>
2. Select **Mail** + **Linux** (or any device)
3. Copy the generated 16-character password → `GMAIL_APP_PASSWORD`

> You must have **2-Step Verification** enabled on your Google account.

---

## API reference

Interactive docs: <http://localhost:8003/docs>

### `GET /health`

```bash
curl http://localhost:8003/health
```

---

### `POST /generate` — generate and store an email

```bash
# Cold outreach to a hiring manager
curl -X POST http://localhost:8003/generate \
     -H "Content-Type: application/json" \
     -d '{
       "job_id":          "3fa85f64-5717-4562-b3fc-2c963f66afa6",
       "contact_id":      "a1b2c3d4-0000-0000-0000-000000000001",
       "template":        "cold_outreach",
       "your_name":       "Vaibhav Sharma",
       "your_stack":      ["Python", "FastAPI", "PostgreSQL"],
       "github_url":      "https://github.com/sharmavaibhav31",
       "graduation_year": 2025
     }'
```
```json
{
  "email_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "subject":  "Backend Engineer opportunity — Vaibhav Sharma",
  "body":     "Hi Alice,\n\nI came across Razorpay's Backend Engineer opening..."
}
```

```bash
# Recruiter outreach
curl -X POST http://localhost:8003/generate \
     -H "Content-Type: application/json" \
     -d '{"job_id": "...", "contact_id": "...", "template": "recruiter_outreach",
          "your_name": "Vaibhav Sharma", "your_stack": ["Go", "Kubernetes"],
          "github_url": "https://github.com/sharmavaibhav31", "graduation_year": 2025}'

# Referral outreach
curl -X POST http://localhost:8003/generate \
     -H "Content-Type: application/json" \
     -d '{"job_id": "...", "contact_id": "...", "template": "referral_outreach",
          "your_name": "Vaibhav Sharma", "your_stack": ["Python", "FastAPI"],
          "github_url": "https://github.com/sharmavaibhav31",
          "referred_by": "Priya Menon"}'

# Follow-up (7 days later)
curl -X POST http://localhost:8003/generate \
     -H "Content-Type: application/json" \
     -d '{"job_id": "...", "contact_id": "...", "template": "followup",
          "your_name": "Vaibhav Sharma", "your_stack": [],
          "github_url": "https://github.com/sharmavaibhav31",
          "availability": "Monday and Wednesday between 2–5 PM IST"}'
```

---

### `GET /emails?job_id={uuid}` — list emails for a job

```bash
curl "http://localhost:8003/emails?job_id=3fa85f64-5717-4562-b3fc-2c963f66afa6"
```

---

### `GET /emails/{id}` — fetch a single email

```bash
curl http://localhost:8003/emails/f47ac10b-58cc-4372-a567-0e02b2c3d479
```

---

### `PATCH /emails/{id}/status` — update status

Valid values: `draft`, `sent`, `replied`.

```bash
curl -X PATCH http://localhost:8003/emails/f47ac10b-.../status \
     -H "Content-Type: application/json" \
     -d '{"status": "replied"}'
```

---

### `POST /emails/{id}/send` — send via Gmail

Fetches the recipient address from the linked contact record. Marks `sent_at` and `status = sent` on success.

```bash
curl -X POST http://localhost:8003/emails/f47ac10b-.../send
```

---

## Template customization

All templates live in `templates/`. Edit them freely — they use standard [Jinja2](https://jinja.palletsprojects.com/) syntax.

Available context variables:

| Variable | Source |
|---|---|
| `company` | jobs table |
| `role` | jobs table |
| `your_name` | request body / `YOUR_NAME` env |
| `your_stack` | request body |
| `github_url` | request body / `YOUR_GITHUB_URL` env |
| `product_observation` | Ollama or fallbacks.yaml |
| `contact_name` | contacts table |
| `graduation_year` | request body |
| `availability` | request body (followup only) |

---

## How the fallback selection works

`fallbacks.yaml` contains observations in 5 categories: `fintech`, `devtools`, `saas`, `ecommerce`, `infra`.

The generator counts keyword matches between the job's `product` + `stack` fields and each category's `keywords` list. The category with the highest score wins, and a random observation from that category's list is chosen. A `default` category is used when no keywords match.
