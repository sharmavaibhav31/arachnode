# Unstop Scraper (unstop.com)

This document describes the Playwright-based `UnstopScraper` implemented in
`scraper-service/scrapers/unstop.py` and how contributors can run, test and
maintain it.

## Purpose

- Scrapes both `/jobs` and `/internships` listing pages on `unstop.com`.
- Uses Playwright to render the Angular SPA so server-hydrated listing cards
  can be parsed reliably.
- Emits normalized job dicts to the `jobs:raw` Redis Stream consumed by the
  Aggregator Service.

## Files

- Scraper implementation: `scraper-service/scrapers/unstop.py`
- Smoke-run helper: `scraper-service/run_unstop.py`
- Unit tests: `tests/unit/test_unstop_parser.py`

## Running locally (developer machine)

1. Create a virtual environment and install dependencies:

```bash
cd scraper-service
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
```

2. Install Playwright Chromium once:

```bash
# from within the activated virtualenv
python -m playwright install chromium
```

3. Run the smoke script to validate parsing (no Redis required):

```bash
python run_unstop.py
```

`run_unstop.py` uses the same parsing logic as the service and will print a
summary of parsed opportunities.

## Docker / CI notes

- Playwright downloads browser binaries (~150–400 MB). For reliable CI and
  Docker runs, browsers should be installed at build time and owned by the
  non-root runtime user.

- The project Dockerfile (`scraper-service/Dockerfile`) has been updated to:
  - Create a non-root `appuser` before installing browsers.
  - Set `PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright`.
  - Run `python -m playwright install chromium` and `chown -R appuser:appuser`
    the resulting cache folder so the `appuser` can access the browser
    binaries at runtime.

- To rebuild the scraper image after changes:

```bash
# from project root
docker compose build --no-cache scraper
docker compose up -d scraper
```

This ensures the Playwright binaries are baked into the image and avoids the
`Executable doesn't exist` runtime error.

## Configuration & runtime hints

- The scraper respects `SCRAPER_DELAY_SECONDS` (minimum 3s for Unstop).
- Limit concurrent Playwright contexts: Unstop is rate-sensitive — run only
  one concurrent context against unstop when scraping.

## Maintenance

- The parser lives in `scraper-service/scrapers/unstop.py` — update the
  regular expressions and `_CARD_SEL` if Unstop's markup changes.
- There are unit tests for the parsing logic in `tests/unit/test_unstop_parser.py`.
  Run them with `pytest tests/unit/test_unstop_parser.py`.

## See also

- Project contribution workflow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Service README and selector reference: `scraper-service/README.md`


