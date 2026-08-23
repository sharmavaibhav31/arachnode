# Agent Search Service

The **Job Search Agent Service** is an on-demand, intent-driven job search engine. Unlike scheduled scrapers, it is triggered interactively by natural language queries typed in the dashboard.

## Features

- **LLM Intent Parsing**: Interprets natural language search requests into structured intents and generates 5–8 targeted Google dorking queries (supports Ollama, OpenAI, Anthropic).
- **Parallel Search Execution**: Executes DuckDuckGo web searches and direct public ATS API calls (Lever, Greenhouse, Ashby) concurrently.
- **Strict Freshness Filtering**: Discards stale job listings older than `max_age_days` (default 14 days) and tags date-unknown jobs.
- **Deterministic Relevance Scoring**: Scores job candidates from 0.0 to 1.0 based on role title keywords, stack tags, location match, and company stage.
- **Live SSE Streaming**: Streams progress states and found job cards live to the dashboard via Server-Sent Events.
- **Redis Pipeline Emission**: Allows users to curate and save specific found jobs directly into the `jobs:raw` Redis Stream pipeline.

## Endpoints

- `GET /health` — Liveness check.
- `POST /search` — Creates search session and returns `search_id`.
- `GET /search/{search_id}/stream` — SSE event stream (`text/event-stream`).
- `POST /search/{search_id}/save` — Emits selected jobs to `jobs:raw` Redis Stream.
- `GET /searches` — Retrieves recent search history.
- `GET /searches/{search_id}` — Retrieves detailed metadata for a search session.
