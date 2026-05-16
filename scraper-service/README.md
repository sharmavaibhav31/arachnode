# Platform Scraper Service

A FastAPI microservice that scrapes **Naukri.com**, **LinkedIn** (public pages only), and **Internshala** for engineering job listings and emits them onto the same `jobs:raw` Redis Stream consumed by the Job Aggregator Service.

```
POST /scrape  →  asyncio.gather([NaukriScraper, LinkedInScraper, IntershalaScraper])
                          ↓ each scraper
                    jobs:raw  Redis Stream  →  Aggregator Service  →  PostgreSQL
```

---

## Project layout

```
scraper-service/
├── main.py                  # FastAPI app — POST /scrape, GET /health
├── emit.py                  # Shared Redis Stream emitter
├── scrapers/
│   ├── __init__.py
│   ├── base.py              # PlatformScraper ABC
│   ├── naukri.py            # httpx + BeautifulSoup (3 pages)
│   ├── linkedin.py          # Playwright headless (public-only)
│   └── internshala.py       # httpx + BeautifulSoup (2 pages)
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `SCRAPER_DELAY_SECONDS` | `3` | Base delay between requests per scraper |

---

## Quick start

### Docker

```bash
# From the project root (requires Redis already running, e.g. from aggregator-service)
cd scraper-service
docker build -t scraper-service .
docker run -e REDIS_HOST=host.docker.internal -p 8001:8000 scraper-service
```

---

## Unstop (playwright)

The repository includes a Playwright-based scraper for Unstop located at
`scraper-service/scrapers/unstop.py`. See `UNSTOP.md` for run instructions,
Docker considerations and parser maintenance notes.


### Local dev

```bash
cd scraper-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium         # download Chromium binary once

export REDIS_HOST=localhost
export REDIS_PORT=6379

uvicorn main:app --reload --port 8001
```

---

## API endpoints

### `GET /health`

```bash
curl http://localhost:8001/health
```
```json
{"status": "ok"}
```

---

### `POST /scrape` — trigger all scrapers

The endpoint returns **immediately**; scraping happens in the background.

```bash
curl -X POST http://localhost:8001/scrape \
     -H "Content-Type: application/json" \
     -d '{"role": "Backend Engineer", "stack": ["Python", "Go"]}'
```
```json
{
  "triggered": true,
  "platforms": ["naukri", "linkedin", "internshala"]
}
```

Jobs flow into the Redis Stream and are picked up by the Aggregator Service automatically.  Query them via:

```bash
curl "http://localhost:8000/jobs?sort=latest&limit=20"
```

---

## Selector reference & maintenance guide

All CSS selectors are defined as **named module-level constants** at the top of each scraper file.  When a platform changes its markup, update only those constants.

### Naukri.com (`scrapers/naukri.py`)

> Naukri delivers most listing data as server-side HTML on the first 3 pages.  
> If they shift to a full JS API, switch to `https://www.naukri.com/jobapi/v3/search?keyword={role}&pageNo={n}`.

| Selector constant | Target element |
|---|---|
| `card_sel` | `article.jobTuple` / `div.srp-jobtuple-root` — one job card |
| `title_sel` | `a.title` / `a.jobTitle` — job title anchor |
| `company_sel` | `a.comp-name` / `span.comp-name` — company name |
| `loc_sel` | `span.loc span a` / `li.location span` — city / location |
| `skills_sel` | `ul.tags-gt li` / `ul.tags li` — skill badge list items |
| `date_sel` | `span.job-post-day` — "3 days ago" text |

URL pattern: `https://www.naukri.com/{role-slug}-jobs?pageNo={1,2,3}`

---

### LinkedIn (`scrapers/linkedin.py`)

> ⚠️ LinkedIn's DOM changes frequently.  Selectors were last verified March 2026.  
> If you see 0 results, inspect the page source and update the constants below.  
> If you are redirected to `/authwall`, your IP has been rate-limited — wait 30–60 min.

| Constant | CSS selector | Notes |
|---|---|---|
| `_CARD_SEL` | `li > div.base-search-card` | Outermost card wrapper |
| `_TITLE_SEL` | `h3.base-search-card__title` | Job title |
| `_COMPANY_SEL` | `h4.base-search-card__subtitle` | Company name |
| `_LOCATION_SEL` | `span.job-search-card__location` | City/country |
| `_LINK_SEL` | `a.base-card__full-link` | Card permalink |
| `_TIME_SEL` | `time` | ISO datetime attribute |

URL pattern: `https://www.linkedin.com/jobs/search/?keywords={role}&location=India&geoId=102713980&f_TPR=r604800`

**Known limitations:**
- `stack` field is always empty (not exposed on listing pages).
- Only ~25 cards are loaded per scroll session (no multi-page support without auth).
- Playwright Chromium adds ~400 MB to the Docker image and 3–5 s cold-start latency.

---

### Internshala (`scrapers/internshala.py`)

> Mostly server-rendered; httpx works well.  CAPTCHA appears after excessive requests.  
> Keep `SCRAPER_DELAY_SECONDS ≥ 2`.

| Selector constant | Target element |
|---|---|
| `card_sel` | `div.individual_internship` — one posting |
| `title_sel` | `h3.job-internship-name a` / `div.profile h3 a` — title anchor |
| `company_sel` | `h4.company-name a` / `div.company_name a` — company |
| `loc_sel` | `a.location_link` — city |
| `skills_sel` | `div.round_tabs_container span.round_tabs` — skill badges |
| `stipend_sel` | `div.stipend_container span.stipend` — stipend/salary (mapped to `product` field) |

URL pattern: `https://internshala.com/jobs/keywords-{role-slug}/` (page 2: `?page=2`)

---

## Rate limiting & operational notes

| Platform | Strategy | Min delay |
|---|---|---|
| Naukri | Randomised delay between pages (`SCRAPER_DELAY_SECONDS ± 1 s`) | 1.5 s |
| LinkedIn | Fixed scroll delay (enforced ≥ 4 s regardless of env var) | 4 s |
| Internshala | Randomised delay between pages | 2 s |

- All scrapers respect a User-Agent that mimics a real Chrome browser.
- The `POST /scrape` endpoint runs all three scrapers **concurrently** via `asyncio.gather`.  
  Total latency is bounded by the slowest scraper (typically LinkedIn Playwright ~20–30 s).
- The service does **not** manage dedup itself — that is handled by the Aggregator Service's Redis dedup key (`dedup:agg:{md5}`).
