# Job Aggregator Service

A FastAPI microservice that consumes normalized job events from the `jobs:raw` Redis Stream (produced by the Scrapy crawler service), deduplicates them, persists to PostgreSQL, and exposes a REST API for querying and managing jobs.

```
┌─────────────────┐    Redis Stream     ┌───────────────────┐    asyncpg    ┌──────────────┐
│  Crawler Service│ ──► jobs:raw ──────► │ Aggregator Service│ ────────────► │  PostgreSQL  │
│  (Scrapy)       │                      │ (FastAPI + asyncio)│              │  jobs table  │
└─────────────────┘                      └───────────────────┘              └──────────────┘
```

## Tech stack

| Layer | Library |
|-------|---------|
| API framework | FastAPI + Uvicorn |
| DB driver | asyncpg (raw SQL, no ORM) |
| Redis client | redis-py (asyncio) |
| Schemas | Pydantic v2 |
| Runtime | Python 3.11 |

---

## Project layout

```
aggregator-service/
├── main.py          # FastAPI app, lifespan, endpoints
├── db.py            # asyncpg pool, schema init, query helpers
├── consumer.py      # Redis Stream consumer loop
├── matcher.py       # Optional SBERT-based semantic job ranking
├── models.py        # Pydantic response schemas
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `DATABASE_URL` | — | asyncpg DSN, e.g. `postgresql://user:pass@host:5432/db` |
| `PORT` | `8000` | Port the API listens on |
| `POSTGRES_USER` | `jobuser` | (docker-compose only) |
| `POSTGRES_PASSWORD` | `jobpass` | (docker-compose only) |
| `POSTGRES_DB` | `jobsdb` | (docker-compose only) |
| `MATCHER_CACHE_DIR` | `/tmp/arachnode_cache` | Directory for resume embedding cache |

---

## Quick start

### With Docker Compose (recommended)

> Run from the `aggregator-service/` directory.

```bash
# 1. Copy and tweak env (optional — defaults work out of the box)
cp .env.example .env    # edit JOBSEEKER_ROLE, JOBSEEKER_STACK, etc.

# 2. Start everything (Redis + Postgres + Crawler + Aggregator)
docker compose up --build

# 3. Once the aggregator is healthy, fire the crawler once
docker compose run --rm crawler scrapy crawl remotive
```

### Local development (no Docker)

```bash
cd aggregator-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export REDIS_HOST=localhost
export REDIS_PORT=6379
export DATABASE_URL="postgresql://jobuser:jobpass@localhost:5432/jobsdb"

uvicorn main:app --reload --port 8000
```

---

## API Reference

Interactive docs: <http://localhost:8000/docs>

### `GET /health` — liveness probe

```bash
curl http://localhost:8000/health
```
```json
{"status": "ok"}
```

---

### `GET /jobs` — list jobs

| Query param | Type | Default | Description |
|---|---|---|---|
| `role` | string | — | Substring match on role title (case-insensitive) |
| `stack` | string | — | Comma-separated tags; returns jobs whose stack contains **all** of them |
| `status` | string | — | `new` \| `applied` \| `ignored` |
| `sort` | string | `latest` | `latest` or `oldest` (by `posted_at`) |
| `limit` | int | `50` | Max results (1–500) |
| `resume` | string | — | Resume text; when provided, jobs are ranked by semantic similarity instead of date |

```bash
# All new jobs
curl "http://localhost:8000/jobs?status=new"

# Backend roles using Python, sorted oldest first
curl "http://localhost:8000/jobs?role=backend&stack=Python&sort=oldest&limit=20"

# Jobs that require both FastAPI and PostgreSQL
curl "http://localhost:8000/jobs?stack=FastAPI,PostgreSQL"

# Jobs ranked by match to a resume
curl "http://localhost:8000/jobs?resume=NLP%20engineer%20with%20HuggingFace%20Transformers%20and%20PyTorch"
```

<details>
<summary>Example response — without resume (existing behaviour)</summary>

```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "company": "Acme Corp",
    "role": "Senior Backend Engineer",
    "source": "remotive",
    "url": "https://remotive.com/jobs/123",
    "stack": ["Python", "FastAPI", "PostgreSQL"],
    "product": "Platform",
    "location": "Remote",
    "posted_at": "2026-03-18T10:00:00Z",
    "status": "new",
    "created_at": "2026-03-19T04:00:00Z",
    "match_score": null,
    "match_tier": null
  }
]
```
</details>

<details>
<summary>Example response — with resume (semantic ranking)</summary>

```json
[
  {
    "id": "xyz789",
    "company": "Sarvam AI",
    "role": "NLP Engineer - Indic Languages",
    "source": "remotive",
    "url": "https://remotive.com/jobs/456",
    "stack": ["PyTorch", "Transformers"],
    "product": "Language Models",
    "location": "Remote",
    "posted_at": "2026-03-18T10:00:00Z",
    "status": "new",
    "created_at": "2026-03-19T04:00:00Z",
    "match_score": 0.6842,
    "match_tier": "strong"
  },
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "company": "Acme Corp",
    "role": "Senior Backend Engineer",
    "source": "remotive",
    "url": "https://remotive.com/jobs/123",
    "stack": ["Python", "FastAPI", "PostgreSQL"],
    "product": "Platform",
    "location": "Remote",
    "posted_at": "2026-03-18T10:00:00Z",
    "status": "new",
    "created_at": "2026-03-19T04:00:00Z",
    "match_score": 0.3201,
    "match_tier": "weak"
  }
]
```

Jobs are sorted by `match_score` descending. `match_tier` is one of `strong` (≥ 0.55), `moderate` (0.40–0.54), or `weak` (< 0.40).
</details>

---

### `GET /jobs/{id}` — get single job

```bash
curl http://localhost:8000/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

Returns `404` if the job is not found.

---

### `PATCH /jobs/{id}/status` — update status

Valid statuses: `new`, `applied`, `ignored`.

```bash
# Mark a job as applied
curl -X PATCH http://localhost:8000/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6/status \
     -H "Content-Type: application/json" \
     -d '{"status": "applied"}'

# Ignore a job
curl -X PATCH http://localhost:8000/jobs/3fa85f64-5717-4562-b3fc-2c963f66afa6/status \
     -H "Content-Type: application/json" \
     -d '{"status": "ignored"}'
```

Returns the updated job record, or `404` if not found.

---

### `GET /stats` — aggregate counts

```bash
curl http://localhost:8000/stats
```
```json
{
  "by_source": {
    "remotive": 142,
    "greenhouse": 37
  },
  "by_status": {
    "new": 155,
    "applied": 18,
    "ignored": 6
  }
}
```

---

## Semantic Job Matching

When a `resume` query param is passed to `GET /jobs`, the aggregator ranks jobs by semantic similarity to the resume using Sentence-BERT instead of returning them by date. When no resume is passed, behaviour is identical to before.

### How it works

```
resume text (query param)
        │
        ▼
resume embedding: disk cache check
        │ hit: load pickle       miss: encode + cache to disk
        ▼
JD text built per job: role + company + stack + product
        │
        ▼
all JDs batch-encoded in one model.encode() call (batch_size=32)
        │
        ▼
cosine similarity computed per job
        │
        ▼
jobs sorted descending by match_score, match_tier attached
```

### Model — all-MiniLM-L6-v2

| Property | Detail |
|---|---|
| Size | ~80MB |
| GPU required | No |
| Loading strategy | Lazy — loads on first request that includes a resume param |
| Strength | Captures semantic meaning, not just keyword overlap |

**Why SBERT over TF-IDF?** TF-IDF only matches on shared words. A resume mentioning "HuggingFace Transformers and PyTorch" would score zero against "NLP Engineer — Indic Languages" because there is no word overlap, even though it is the correct top match. SBERT encodes meaning and ranks it correctly.

### Installation

Semantic matching requires one additional package not in the base `requirements.txt`:

```bash
pip install sentence-transformers
```

If `sentence-transformers` is not installed, the matcher silently disables itself and `GET /jobs` continues to work normally — jobs are returned unranked and no error is thrown.

### Caching

Resume embeddings are cached to disk so the same resume text is never encoded twice, even across app restarts.

| Property | Detail |
|---|---|
| Location | `/tmp/arachnode_cache` (override with `MATCHER_CACHE_DIR`) |
| Key | MD5 hash of resume text |
| Format | Pickle — `resume_<hash>.pkl` |
| Invalidation | Different resume text → different hash → new file. No TTL. |

Only resume embeddings are cached. JD embeddings are recomputed per request via batch encoding.

To clear the cache manually:
```bash
rm -rf /tmp/arachnode_cache
```

### Fallback behaviour

| Condition | Result |
|---|---|
| No `resume` param | Date-ordered response, `match_score`/`match_tier` null |
| Empty or whitespace resume | Jobs returned unranked, warning logged |
| `sentence-transformers` not installed | Jobs returned unranked, warning logged |

The endpoint never returns a 500 due to matcher failure.

### Running matcher tests

```bash
cd aggregator-service
python test_matcher_final.py
```

Covers: ranking output, cache hit behaviour, empty resume handling, top match accuracy, worst match accuracy.

---

## How deduplication works

Each incoming event is hashed using **MD5(normalised_company + "|" + normalised_role)**.

- Before inserting, the service checks whether the Redis key `dedup:agg:{hash}` exists.
- If it exists → event is ACK-ed and skipped.
- If not → job is inserted into Postgres and the key is set with a **7-day TTL**.

This prevents the same role from being re-inserted if the crawler runs multiple times per day.

---

## Consumer group & crash recovery

The service subscribes as consumer group `aggregator-group` on the `jobs:raw` stream.  
On startup it runs `XAUTOCLAIM` to reclaim any messages that were delivered but never ACK-ed (e.g. after a crash), ensuring **at-least-once delivery**.

---

## Database schema

```sql
CREATE TABLE jobs (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  company    TEXT        NOT NULL,
  role       TEXT        NOT NULL,
  source     TEXT,
  url        TEXT,
  stack      TEXT[],
  product    TEXT,
  location   TEXT,
  posted_at  TIMESTAMPTZ,
  status     TEXT        NOT NULL DEFAULT 'new',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_jobs_stack     ON jobs USING GIN (stack);
CREATE INDEX idx_jobs_posted_at ON jobs (posted_at DESC NULLS LAST);
CREATE INDEX idx_jobs_status    ON jobs (status);
```