# Crawler Service

## Request/Data Flow

1. Scrapy spiders (e.g., remotive_spider, wellfound_spider) crawl job boards, yielding job items with company, role, stack, etc.
2. Items pass through pipelines: `DeduplicationPipeline` checks for duplicates, `StackFilterPipeline` filters by target stack/role, `RedisStreamPipeline` emits to 'jobs:raw' Redis stream.
3. `read_stream.py` monitors the Redis stream, displaying new job events in real-time or dumping historical entries.

## Internal Execution Pipeline

- **Spider Parsing**: Base spider classes use `stack_matches()` and `role_matches()` to filter jobs based on JOBSEEKER_STACK and JOBSEEKER_ROLE settings.
- **Deduplication Pipeline**: `dedup_pipeline.py` uses Redis keys for URL-based deduplication, skipping already-seen jobs.
- **Stack Filter Pipeline**: `filter_pipeline.py` applies stack intersection checks, dropping items that don't match target technologies.
- **Redis Emit Pipeline**: `emit_pipeline.py` serializes items to JSON strings, adds to 'jobs:raw' stream with maxlen 10,000, logging emissions.
- **Stream Monitoring**: `read_stream.py` uses Redis XREAD/XREVRANGE for tailing or dumping stream contents, formatting job details.

## Important Modules/Files

- `read_stream.py`: CLI script for Redis stream monitoring with options for tailing, dumping, and count limits.
- `scrapy.cfg`: Scrapy project configuration pointing to crawler.settings.
- `crawler/settings.py`: Scrapy settings with politeness delays, Playwright middleware, pipeline order, Redis connection, and jobseeker profile.
- `crawler/spiders/base_spider.py`: Abstract base spider with stack/role matching logic and crawler instantiation.
- `crawler/pipelines/emit_pipeline.py`: Final pipeline stage emitting job items to Redis stream with JSON serialization and maxlen capping.

## Service Interactions

- Crawls external job board websites (Remotive, Wellfound, YC, Naukri, LinkedIn) using Scrapy with Playwright for JavaScript rendering.
- Writes job events to Redis 'jobs:raw' stream, consumed by aggregator-service for database insertion.
- Uses Redis for deduplication keys and stream storage.

## Debugging Notes

- Spider logs include parse successes/failures, with debug level for filtered items.
- Pipeline logs emission counts and skipped duplicates, with warnings for Redis connection issues.
- Playwright timeouts logged as errors, with AUTOTHROTTLE adjusting delays for rate limiting.
- Stream monitoring logs connection errors if Redis is unreachable.
- Item serialization errors in emit_pipeline logged as exceptions, potentially dropping malformed items.
- Concurrent requests limited to 4 globally, 1 per domain, to avoid bans.
