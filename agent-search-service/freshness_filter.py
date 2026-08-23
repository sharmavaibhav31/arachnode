"""
freshness_filter.py — Strict date parsing and age filtering for job results.

Extracts posted_at dates from various formats (ISO 8601, Unix ms, relative strings, human dates)
and discards jobs older than max_age_days. Unknown dates are kept with date_unknown=True
and sorted after known dates.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_date(raw_date: Any) -> Optional[datetime]:
    """Parse raw date representation into UTC datetime object."""
    if not raw_date:
        return None

    now = datetime.now(timezone.utc)

    # 1. Numeric timestamp (seconds or milliseconds)
    if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.isdigit()):
        val = float(raw_date)
        if val > 1e11:  # milliseconds
            val /= 1000.0
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None

    if not isinstance(raw_date, str):
        return None

    s = raw_date.strip().lower()

    # 2. Relative date strings
    if "today" in s or "just now" in s or "hour ago" in s or "hours ago" in s or "minute" in s:
        return now

    if "yesterday" in s:
        return now - timedelta(days=1)

    m = re.search(r'(\d+)\s*(day|days|d)\s*ago', s)
    if m:
        days = int(m.group(1))
        return now - timedelta(days=days)

    m = re.search(r'(\d+)\s*(week|weeks|w)\s*ago', s)
    if m:
        weeks = int(m.group(1))
        return now - timedelta(days=weeks * 7)

    m = re.search(r'(\d+)\s*(month|months|m)\s*ago', s)
    if m:
        months = int(m.group(1))
        return now - timedelta(days=months * 30)

    # 3. ISO 8601 strings
    clean_iso = raw_date.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # 4. Standard strptime patterns
    patterns = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%d %b %Y",
    ]
    for fmt in patterns:
        try:
            dt = datetime.strptime(raw_date.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def filter_by_freshness(jobs: List[Dict[str, Any]], max_age_days: int) -> Tuple[List[Dict[str, Any]], int]:
    """
    Returns (kept_jobs, discarded_count).
    Jobs with unknown dates are kept but marked date_unknown=True.
    Jobs are sorted by posted_at DESC (unknown dates go last).
    """
    kept: List[Dict[str, Any]] = []
    discarded = 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)

    for job in jobs:
        posted_at = _parse_date(job.get("posted_at"))

        if posted_at is None:
            job["posted_at"] = None
            job["date_unknown"] = True
            job["days_ago"] = None
            kept.append(job)
        elif posted_at < cutoff:
            discarded += 1
        else:
            job["posted_at"] = posted_at.isoformat()
            job["date_unknown"] = False
            days_diff = (now - posted_at).days
            job["days_ago"] = max(0, days_diff)
            kept.append(job)

    # Sort: known dates newest first, unknowns at the end
    kept.sort(key=lambda j: (
        j.get("date_unknown", True),
        -(datetime.fromisoformat(j["posted_at"]).timestamp() if j.get("posted_at") else 0)
    ))

    return kept, discarded
