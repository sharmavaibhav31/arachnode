# Aggregator Service

## Request/Data Flow

1. `GET /jobs` accepts query parameters for role, stack, status, sort, and limit, querying PostgreSQL with filters and returning job records.
2. `GET /jobs/{id}` fetches a single job by UUID from PostgreSQL.
3. `PATCH /jobs/{id}/status` updates the job status in PostgreSQL and returns the updated record.
4. `GET /stats` aggregates counts by source and status from PostgreSQL.
5. Background consumer reads messages from Redis 'jobs:raw' stream, parses fields, checks deduplication key, and conditionally inserts into PostgreSQL.

## Internal Execution Pipeline

- **Consumer Loop**: `consumer.run_consumer()` connects to Redis, ensures consumer group exists, claims pending messages, then reads in batches using `XPENDING` and `XREADGROUP`, processing each message asynchronously.
- **Message Processing**: `_process_message()` decodes stream fields, normalizes company/role for deduplication, checks Redis key existence, parses stack as JSON array and posted_at as datetime, then calls `db.insert_job()` with conflict resolution.
- **Deduplication**: `_dedup_key()` generates MD5 hash from normalized company+role, sets Redis key with 7-day TTL on successful insert to prevent reprocessing.
- **Database Operations**: `db.insert_job()` uses `INSERT ... ON CONFLICT DO NOTHING` for URL uniqueness, `get_jobs()` applies ILIKE for role substring and GIN containment for stack arrays, with sorting by posted_at.
- **Stats Aggregation**: `db.get_stats()` executes GROUP BY queries on source and status columns, returning dictionaries of counts.

## Important Modules/Files

- `main.py`: FastAPI application with endpoints (`/jobs`, `/jobs/{id}`, `/jobs/{id}/status`, `/stats`), lifespan hooks for pool and consumer task management, and Pydantic response models.
- `consumer.py`: Async Redis stream consumer with consumer group management, message parsing, deduplication logic, and batch processing using `XAUTOCLAIM` for pending messages.
- `db.py`: asyncpg pool lifecycle, schema DDL for jobs table with GIN/BTREE indexes, and CRUD functions with parameterized queries and conflict handling.
- `models.py`: Pydantic models for `JobOut`, `StatusUpdate`, and `StatsOut` with validation for status values and attribute-based configuration.

## Service Interactions

- Consumes messages from Redis 'jobs:raw' stream using consumer groups for reliable delivery.
- Writes job records to PostgreSQL jobs table, shared with other services like contact-discovery-service and email-generator-service.
- Provides REST API for job queries and status updates, consumed by gateway or other components.

## Debugging Notes

- Consumer logs warnings for missing company/role in messages, debug for duplicates skipped, and info for successful inserts with job IDs.
- Database connection errors raise `RuntimeError` if pool is uninitialized, logged during lifespan startup.
- Redis connection issues in consumer loop may cause retries, with group creation errors logged as info if already exists.
- Query timeouts in `db.py` default to 30 seconds, potentially delaying API responses under high load.
- Deduplication key collisions logged as debug, with MD5 hash generation ensuring consistent keying.
