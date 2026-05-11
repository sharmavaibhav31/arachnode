# Scheduler Service

## Request/Data Flow

1. APScheduler runs `run_scrape_cycle()` every CRAWL_INTERVAL_HOURS: POST /api/scrape to gateway, runs Scrapy subprocess for remotive/yc_jobs spiders, waits for pipelines, counts job delta.
2. APScheduler runs `run_discover_cycle()` every DISCOVER_INTERVAL_HOURS: fetches new jobs via GET /api/jobs, POST /api/discover for each job with delay between calls.
3. APScheduler runs `run_draft_cycle()` every DISCOVER_INTERVAL_HOURS: fetches new jobs, checks for contacts via GET /api/contacts, POST /api/generate for jobs with contacts.
4. After each task, summary is written to /data/run_summary.json with jobs_discovered, contacts_found, emails_drafted, errors.

## Internal Execution Pipeline

- **Scrape Cycle**: `tasks.run_scrape_cycle()` counts jobs before, triggers platform scrapers via httpx POST, runs Scrapy subprocess with timeout, waits SCRAPER_WAIT_SECS, counts delta and updates summary.
- **Discover Cycle**: `tasks.run_discover_cycle()` fetches new jobs via httpx GET, loops over jobs, POST /api/discover with DISCOVER_DELAY_SECS pause, increments contacts_found on success.
- **Draft Cycle**: `tasks.run_draft_cycle()` fetches new jobs, checks contacts via GET /api/contacts, generates drafts via POST /api/generate for jobs with contacts, updates emails_drafted.
- **Summary Flushing**: `main._write_summary()` serializes summary dict to JSON file, logged on success/failure.
- **Manual Runs**: `main._maybe_manual_run()` dispatches single tasks or all via MANUAL_TASK env var, exits after completion.

## Important Modules/Files

- `main.py`: APScheduler setup with interval jobs for scrape/discover/draft, graceful shutdown handling, summary writing, manual task dispatch.
- `tasks.py`: Synchronous task functions with httpx calls to gateway, subprocess for Scrapy, summary state management, error recording.
- `logger.py`: JSONFormatter for structured logging to stdout, StructLogger adapter for extra fields.

## Service Interactions

- Calls gateway /api/scrape, /api/jobs, /api/discover, /api/contacts, /api/generate via httpx.
- Runs Scrapy subprocess for crawler-service spiders.
- Writes run summary to shared Docker volume /data/run_summary.json, read by gateway.

## Debugging Notes

- Task exceptions logged as JSON with context/detail, appended to summary errors.
- HTTP timeouts/failures logged in tasks, with _record_error() updating summary.
- Subprocess timeouts/errors logged, with stderr captured in summary.
- Scheduler misfires logged via APScheduler, with grace time 300s.
- Manual runs exit after task, useful for testing without schedule.
- Concurrent tasks prevented by _task_lock, with warnings for skipped runs.
