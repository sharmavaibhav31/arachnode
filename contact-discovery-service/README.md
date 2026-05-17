# Contact Discovery Service

## Request/Data Flow

1. `POST /discover` accepts company name, optional job_id, roles list, and domain, triggering background discovery pipeline.
2. Background task calls `discovery.run_pipeline()` to execute stages: domain inference, pattern detection, name discovery, email construction, and SMTP verification.
3. Verified contacts are upserted into PostgreSQL via `storage.upsert_contact()` with conflict resolution on (company, email).
4. `GET /contacts?company={company}` queries PostgreSQL for contacts by company substring match.
5. `GET /contacts/{job_id}` retrieves contacts linked to a specific job UUID.
6. `DELETE /contacts/{id}` removes a contact record from PostgreSQL.

## Internal Execution Pipeline

- **Domain Inference**: `domain_inference()` queries Clearbit autocomplete API, falls back to direct HTTPS probes of common suffixes (com, io, co.in) to determine company domain.
- **Email Pattern Detection**: `email_pattern_detection()` searches GitHub commits and org members for domain emails, infers patterns (e.g., {first}.{last}@{domain}) using regex matching, defaults to {first}.{last} if undetected.
- **Name Discovery**: `_github_org_names()` fetches GitHub org members' public profiles for names/roles, supplemented by LinkedIn search parsing for additional contacts.
- **Email Construction**: Combines discovered names with inferred pattern to generate email addresses.
- **SMTP Verification**: `verifier.verify_email()` resolves MX records, performs SMTP RCPT TO checks with per-domain rate limiting (5/hour), returning 'verified', 'unverified', or 'invalid'.
- **Storage Upsert**: `storage.upsert_contact()` uses `INSERT ... ON CONFLICT (company, email) DO UPDATE` to merge new data with existing records.

## Important Modules/Files

- `main.py`: FastAPI application with endpoints (`/discover`, `/contacts`, `/contacts/{job_id}`, `/contacts/{id}`), background task management, and Pydantic models for requests/responses.
- `discovery.py`: Multi-stage pipeline using httpx for HTTP requests, GitHub API for name/pattern mining, and regex for email pattern inference.
- `storage.py`: asyncpg pool lifecycle, schema DDL for contacts table with indexes, and CRUD functions with unique constraint on (company, email).
- `verifier.py`: SMTP verification with dnspython MX resolution, rate limiting via in-memory dict, and synchronous SMTP checks wrapped in asyncio executor.

## Service Interactions

- Reads jobs table from PostgreSQL to link contacts to job postings.
- Writes contacts records to PostgreSQL, shared with email-generator-service for recipient lookup.
- Makes external HTTP requests to Clearbit, GitHub API, and LinkedIn for public data mining.
- Performs SMTP connections to domain MX servers for email verification.

## Debugging Notes

- Domain inference logs Clearbit successes/failures as info/debug, with warnings for unresolved domains.
- GitHub API errors logged as debug, with rate limit handling via optional GITHUB_TOKEN.
- SMTP verification logs results per email, with rate limit warnings and connection errors as debug.
- Database upsert conflicts logged implicitly via ON CONFLICT, with unique constraint added dynamically.
- Pipeline stage failures in `discovery.py` may skip to next stage, logged with exceptions.
- Asyncpg timeouts default to 30 seconds, potentially affecting contact listing under load.
