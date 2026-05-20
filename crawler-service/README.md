# Crawler Service

Part of the Arachnode microservice system. This service crawls startup job
directories and career pages, filters results by your role and stack, deduplicates
them via Redis, and emits normalized `JobPosting` events onto a Redis Stream for
downstream services to consume.

---

## Project structure

```
crawler-service/
├── crawler/
│   ├── spiders/
│   │   ├── base_spider.py        # shared rate limiting and stack matching
│   │   ├── yc_spider.py          # YC jobs page (plain HTML, fastest)
│   │   ├── wellfound_spider.py   # Wellfound / AngelList (Playwright)
│   │   └── remotive_spider.py    # Remotive JSON API (most reliable)
│   ├── parsers/
│   │   ├── ats_detector.py       # Lever / Greenhouse / Ashby API clients
│   │   └── generic_parser.py     # Playwright fallback for custom career pages
│   ├── pipelines/
│   │   ├── dedup_pipeline.py     # Redis-based dedup (7-day TTL)
│   │   ├── filter_pipeline.py    # Stack and role matching
│   │   └── emit_pipeline.py      # Push to Redis Stream jobs:raw
│   ├── models.py                 # JobItem and JobPosting dataclass
│   ├── settings.py               # Scrapy config
│   └── middlewares.py            # User-agent rotation
├── tests/
│   └── test_ats_detector.py
├── read_stream.py                # Monitor Redis Stream output
├── run_local.sh                  # Run without Docker
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Quickstart (local, no Docker)

### 1. Prerequisites

- Python 3.11+
- Redis running on localhost:6379
  ```bash
  # macOS
  brew install redis && brew services start redis
  # Ubuntu
  sudo apt install redis-server && sudo systemctl start redis
  ```

### 2. Set up the Python environment

```bash
cd crawler-service
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium    # one-time browser install (~150MB)
```

### 3. Run your first spider

Start with Remotive — it uses a public JSON API, never breaks, and is a
perfect way to verify the pipeline end-to-end before touching scrapers.

```bash
# Edit your profile first, then:
export JOBSEEKER_ROLE="Backend Engineer"
export JOBSEEKER_STACK="Python,Go,FastAPI,PostgreSQL,Kubernetes"

scrapy crawl remotive
```

Or use the convenience script:
```bash
chmod +x run_local.sh
./run_local.sh remotive
```

### 4. Check what was emitted

```bash
python read_stream.py --count 20     # see last 20 jobs
python read_stream.py --all          # dump everything
python read_stream.py                # tail new events live
```

---

## Quickstart (Docker)

```bash
docker-compose up --build
```

This starts Redis + the crawler (Remotive spider by default).
To run a different spider:

```bash
docker-compose run crawler scrapy crawl wellfound
docker-compose run crawler scrapy crawl yc_jobs
```

---

## Available spiders

| Spider | Source | JS needed | Notes |
|--------|--------|-----------|-------|
| `remotive` | remotive.com API | No | Best first spider to test with |
| `yc_jobs` | ycombinator.com/jobs | No | YC-backed companies only |
| `wellfound` | wellfound.com | Yes (Playwright) | Best breadth of funded startups |

---

## Configuring your profile

Edit in `settings.py` or pass as environment variables / `-s` flags:

```bash
scrapy crawl remotive \
  -s JOBSEEKER_ROLE="Full Stack Engineer" \
  -s JOBSEEKER_STACK="React,Node.js,PostgreSQL,AWS"
```

Stack matching is OR-based — a job passes if *any* of your stack tags appear
in the posting's tags or role title.

---

## Using the ATS parsers directly

The Lever and Greenhouse parsers can be used standalone to pull jobs from any
company that uses these systems:

```python
from crawler.parsers.ats_detector import fetch_lever_jobs, fetch_greenhouse_jobs

# Get all open roles at Razorpay (Lever)
jobs = fetch_lever_jobs("razorpay")

# Get all open roles at Notion (Greenhouse)
jobs = fetch_greenhouse_jobs("notion")

for job in jobs:
    print(job["role"], "—", job["url"])
```

---

## Extending with a new spider

1. Create `crawler/spiders/mysite_spider.py`
2. Subclass `BaseStartupSpider`
3. Implement `parse(self, response)` and yield `JobItem` objects
4. That's it — the pipelines (dedup, filter, emit) run automatically

```python
from crawler.spiders.base_spider import BaseStartupSpider
from crawler.models import JobItem

class MySiteSpider(BaseStartupSpider):
    name = "mysite"
    start_urls = ["https://example.com/jobs"]

    def parse(self, response):
        for job in response.css("div.job"):
            role = job.css("h3::text").get("")
            if self.role_matches(role):
                yield JobItem(
                    company="Example Corp",
                    role=role,
                    source=self.name,
                    url=response.url,
                    stack=[],
                )
```

---

## Running tests

```bash
pytest tests/ -v
```

---

## Scheduling (cron)

To run automatically every 8 hours:

```bash
crontab -e
```

Add:
```
0 */8 * * * cd /path/to/crawler-service && source venv/bin/activate && scrapy crawl remotive >> logs/remotive.log 2>&1
0 */8 * * * cd /path/to/crawler-service && source venv/bin/activate && scrapy crawl yc_jobs  >> logs/yc.log 2>&1
```

---

## Troubleshooting

**Redis connection refused**
Make sure Redis is running: `redis-cli ping` should return `PONG`.

**Playwright: browser not found**
Run `playwright install chromium` inside your virtualenv.

**Wellfound returns nothing**
Wellfound has aggressive bot detection. Add a longer delay:
`scrapy crawl wellfound -s DOWNLOAD_DELAY=5`

**Stream is empty after a run**
Check that items aren't all being dropped by the filter pipeline.
Run with `-s LOG_LEVEL=DEBUG` to see drop reasons.

**Items showing as duplicates immediately**
The dedup TTL is 7 days. To reset: `redis-cli DEL $(redis-cli KEYS "dedup:*")`
