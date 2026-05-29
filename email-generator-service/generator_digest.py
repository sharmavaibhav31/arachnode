"""
generator_digest.py — Weekly digest email generator.
 
Kept intentionally separate from generator.py so the existing
single-email generation pipeline is not touched at all.
 
Pipeline:
  1. Receive a flat list of job dicts from the caller.
  2. Filter out jobs older than MAX_AGE_DAYS (staleness guard).
  3. Group the remaining jobs by their 'source' field.
  4. Render digest.j2 with the grouped data.
  5. Return (subject, body) strings — identical contract to generator.generate_email().
 
The caller (main.py /digest endpoint) handles SMTP sending
via the existing mailer.send_email(), so no SMTP logic lives here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)
_TEMPLATE_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",)),
    trim_blocks=True,
    lstrip_blocks=True,
)
MAX_AGE_DAYS = 7


def generate_digest(
    *,
    jobs: list[dict[str, Any]],
    your_name: str,
    week_label: str,
) -> tuple[str, str]:
    if jobs is None:
        raise ValueError("jobs must be a list, got None")

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    recent_jobs: list[dict[str, Any]] = []

    for job in jobs:
        posted_raw = job.get("posted_at")

        if posted_raw is None:
            recent_jobs.append(job)
            continue

        try:
            posted_dt = datetime.fromisoformat(str(posted_raw))
            if posted_dt.tzinfo is None:
                posted_dt = posted_dt.replace(tzinfo=timezone.utc)

            if posted_dt >= cutoff:
                recent_jobs.append(job)
            else:
                logger.debug(
                    "Digest: skipping stale job %s @ %s (posted %s)",
                    job.get("role"),
                    job.get("company"),
                    posted_raw,
                )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Digest: could not parse posted_at=%r for %s @ %s — including anyway: %s",
                posted_raw,
                job.get("role"),
                job.get("company"),
                exc,
            )
            recent_jobs.append(job)

    logger.info(
        "Digest: %d total jobs → %d fresh (cutoff: %s)",
        len(jobs),
        len(recent_jobs),
        cutoff.isoformat(),
    )

    jobs_by_source: dict[str, list[dict[str, Any]]] = {}
    for job in recent_jobs:
        source = job.get("source") or "unknown"
        jobs_by_source.setdefault(source, []).append(job)

    context: dict[str, Any] = {
        "your_name": your_name,
        "job_count": len(recent_jobs),
        "week_label": week_label,
        "jobs_by_source": jobs_by_source,
        "sources_count": len(jobs_by_source),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    template = _jinja_env.get_template("digest.j2")
    rendered_text = template.render(**context)

    lines = rendered_text.strip().splitlines()
    subject = ""
    body_lines: list[str] = []

    for i, line in enumerate(lines):
        if i == 0 and line.lower().startswith("subject:"):
            subject = line[len("subject:") :].strip()
        elif i == 1:
            continue
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    logger.info("Digest email rendered — subject: %s", subject)

    return subject, body
