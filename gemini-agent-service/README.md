# Gemini Agent Service (Service 8)

The **Gemini Agent Service** is an AI assistant microservice powered by the Google Gemini API (`gemini-2.0-flash`). It provides conversational job search assistance, resume tuning for specific job descriptions, and customized cold email drafting.

---

## Capabilities

1. **AI Job Search:** Integrates with the Arachnode pipeline and open web search (DuckDuckGo) to discover fresh software engineering opportunities.
2. **Resume Tuning:** Evaluates keyword gaps and rewrites bullet points to match target job descriptions without fabricating experience.
3. **Cold Email Drafting:** Generates personalized outreach drafts (<150 words) targeting specific companies and hiring managers.

---

## Configuration

Set `GEMINI_API_KEY` in your `.env` file:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```
Get a free API key at: [Google AI Studio](https://aistudio.google.com/apikey)

If `GEMINI_API_KEY` is omitted, the service gracefully degrades and `/agent/chat` returns HTTP 503 while all other Arachnode microservices function normally.

---

## Endpoints

- `GET /health` — Health and configuration probe.
- `POST /agent/chat` — Conversational AI agent endpoint.
- `POST /agent/enhance-resume` — Direct resume enhancement against a job description.
- `POST /agent/draft-email` — Direct cold email drafting.
- `GET /agent/sessions/{session_id}` — Session history retrieval.
