"""Quick smoke test — runs UnstopScraper and prints 5 sample results."""
import asyncio, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from scrapers.unstop import UnstopScraper

async def main():
    scraper = UnstopScraper()
    jobs = await scraper.scrape("Backend Engineer", ["Python", "FastAPI"])
    print(f"\nTotal scraped: {len(jobs)}\n")
    for job in jobs[:5]:
        print(json.dumps(job, indent=2))
        print("---")

asyncio.run(main())