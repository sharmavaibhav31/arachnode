# Scraper Service

## Request/Data Flow

1. `POST /scrape` accepts role and stack parameters, triggering background concurrent scraping of Naukri, LinkedIn, and Internshala.
2. Each scraper (NaukriScraper, LinkedInScraper, IntershalaScraper) runs asynchronously, returning job dicts with company, role, url, etc.
3. `emit.emit_jobs()` pushes each job dict to the 'jobs:raw' Redis stream, serializing stack to JSON and capping stream length at 50,000.
4. Background task completes, logging emission counts per platform.

## Internal Execution Pipeline

- **Scraper Execution**: `main._run_all_scrapers()` uses `asyncio.gather()` to run all platform scrapers in parallel, capturing exceptions per scraper.
- **LinkedIn Scraping**: `linkedin.LinkedInScraper.scrape()` launches Playwright browser, navigates to search URL, scrolls to load cards, parses selectors for title, company, location, URL, and posted date.
- **Emission Process**: `emit.emit_job()` normalizes fields, checks for required company/role, adds to Redis stream with maxlen and approximate trimming.
- **Error Handling**: Scraper exceptions logged as errors, emission failures logged with exceptions, skipping malformed jobs.

## Important Modules/Files

- `main.py`: FastAPI application with /scrape endpoint, background task management, and concurrent scraper execution.
- `emit.py`: Async Redis emitter with connection pooling, job normalization, and stream addition with maxlen capping.
- `scrapers/base.py`: Abstract base class defining scraper contract with source_name and scrape() method.
- `scrapers/linkedin.py`: Playwright-based LinkedIn scraper with selector parsing, scroll delays, and auth-wall detection.

## Service Interactions

- Scrapes job listings from Naukri, LinkedIn public search, and Internshala using HTTP requests and Playwright for JavaScript sites.
- Emits job events to Redis 'jobs:raw' stream, consumed by aggregator-service for database storage.
- Uses Redis for stream storage and emission.

## Debugging Notes

- Scraper logs include job counts per platform, with errors for exceptions during scraping.
- Playwright timeouts and selector failures logged as warnings/debug, with auth redirects indicating rate limits.
- Emission logs debug-level for each job, with exceptions for Redis connection issues.
- Concurrent scraper runs may have varying completion times, logged per platform.
- Stream maxlen may drop old events if emission rate exceeds consumption.
- Selector updates required when LinkedIn changes markup, logged as parsing errors.
