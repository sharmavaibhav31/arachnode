# Referral Outreach Service

The **Referral Outreach Service** is a microservice within the Arachnode system that parses LinkedIn connections CSV exports, classifies connections by role (HR, Technical, Leadership, Other), generates personalized outreach message drafts, queues messages for manual sending, and provides a dashboard workflow.

> ⚠️ **Important Safety Note**: This service **NEVER** sends messages automatically. Automated messaging on LinkedIn violates LinkedIn Terms of Service and causes account bans. The service drafts, queues, and tracks outreach. Sending is performed manually by the user with one-click copy.

---

## Features

- **LinkedIn Connections CSV Import**: Handles 3-line header/notes metadata automatically.
- **Role Classification**: Deterministic priority matching (`hr` > `leadership` > `technical` > `other` > `unknown`).
- **Templated Outreach Drafts**: Jinja2 templates tailored to connection role type.
- **Daily Queue Management**: Queue 10-15 messages per day to maintain safe outreach cadence.
- **Dashboard Interface**: One-click copy, status tracking (pending, queued, sent, replied, skipped), and statistics.

---

## Architecture

- **Framework**: FastAPI + Uvicorn
- **Database**: PostgreSQL (`referral_contacts` table) via `asyncpg`
- **Port**: `8011`

---

## API Endpoints

- `POST /import`: Upload LinkedIn `connections.csv` file.
- `GET /contacts`: Query paginated contacts with filtering by `type`, `status`, and `company`.
- `GET /contacts/{id}`: Retrieve a specific contact.
- `PATCH /contacts/{id}`: Update contact `status`, `notes`, or `message_draft`.
- `POST /contacts/{id}/regenerate`: Re-render draft using template & current config.
- `GET /queue/today`: Get contacts queued for today's date.
- `POST /queue/generate`: Select pending contacts & queue them for a given date.
- `POST /queue/mark-sent`: Mark specified contacts as sent.
- `GET /stats`: Get system-wide counts and daily metrics.
- `GET /health`: Health check endpoint.
