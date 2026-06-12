"""
Centralized date normalization for the aggregator.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

logger = logging.getLogger(__name__)


DateInput = Optional[Union[str, int, float, datetime]]

_EXPLICIT_FORMATS = [
    # ISO-like without tz
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    # Human-readable locale strings
    "%b %d, %Y",        # Jun 1, 2024
    "%B %d, %Y",        # June 1, 2024
    "%d %b %Y",         # 01 Jun 2024
    "%d %B %Y",         # 01 June 2024
    "%B %d %Y",         # June 1 2024  
    "%b %d %Y",         # Jun 1 2024
    "%d-%m-%Y",         # 01-06-2024 
                        
]

_RELATIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^just\s*now$", re.I),                              "now"),
    (re.compile(r"^today$", re.I),                                   "now"),
    (re.compile(r"^yesterday$", re.I),                               "days:1"),
    (re.compile(r"^(\d+)\s+second[s]?\s+ago$", re.I),               "seconds"),
    (re.compile(r"^(\d+)\s+minute[s]?\s+ago$", re.I),               "minutes"),
    (re.compile(r"^(\d+)\s+hour[s]?\s+ago$", re.I),                 "hours"),
    (re.compile(r"^(\d+)\s+day[s]?\s+ago$", re.I),                  "days"),
    (re.compile(r"^(\d+)\s+week[s]?\s+ago$", re.I),                 "weeks"),
    (re.compile(r"^(\d+)\s+month[s]?\s+ago$", re.I),                "months"),
]

# Heuristic threshold
_MS_THRESHOLD = 1e10

# Internal helpers


def _utcnow() -> datetime:
    """Current UTC time.  Isolated so tests can monkeypatch it."""
    return datetime.now(tz=timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    """Attach UTC if naive, convert to UTC if offset-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _try_iso8601(value: str) -> Optional[datetime]:
   
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _to_utc(dt)
    except ValueError:
        return None


def _try_explicit_formats(value: str) -> Optional[datetime]:

    for fmt in _EXPLICIT_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return _to_utc(dt)
        
        except ValueError:
            continue
    return None


def _try_unix_timestamp(value: Union[str, int, float]) -> Optional[datetime]:
  
    try:
        ts = float(value)

    except (TypeError, ValueError):
        return None

    now_s = time.time()
    if ts < 0:
        return None

    if ts > _MS_THRESHOLD:
        ts /= 1000.0  

  
    if ts > now_s + 50 * 365.25 * 86400:

        logger.warning("normalize_date: timestamp %s is implausibly far in the future — skipping", value)
        return None

    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _try_relative(value: str) -> Optional[datetime]:
 
    v = value.strip()
    now = _utcnow()

    for pattern, unit in _RELATIVE_PATTERNS:
        m = pattern.match(v)
        if m is None:
            continue

        if unit == "now":
            return now

        if unit == "days:1":          
            return now - timedelta(days=1)

        n = int(m.group(1))

        if unit == "seconds":
            return now - timedelta(seconds=n)
        
        if unit == "minutes":
            return now - timedelta(minutes=n) 
        
        if unit == "hours":
            return now - timedelta(hours=n)
        
        if unit == "days":
            return now - timedelta(days=n)
        
        if unit == "weeks":
            return now - timedelta(weeks=n)
        
        if unit == "months":

            return now - timedelta(days=n * 30)

    return None


def normalize_date(value: DateInput) -> Optional[datetime]:


    if isinstance(value, datetime):
        return _to_utc(value)

    
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    # Numeric types
    if isinstance(value, (int, float)):
        result = _try_unix_timestamp(value)
        if result is None:
            logger.warning("normalize_date: could not parse numeric value %r", value)
        return result

    # String that looks purely numeric 
    if isinstance(value, str):
        stripped = value.strip()

        if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
            result = _try_unix_timestamp(stripped)
            if result is None:
                logger.warning("normalize_date: numeric string %r failed timestamp parse", stripped)
            return result

        # ISO 8601 with tz offset
        if "T" in stripped or stripped.endswith("Z"):
            result = _try_iso8601(stripped)
            if result is not None:
                return result
           

        # Explicit formats
        result = _try_explicit_formats(stripped)
        if result is not None:
            return result

        # Relative strings
        result = _try_relative(stripped)
        if result is not None:
            return result

   
        logger.warning(
            "normalize_date: unrecognized date string %r — will fall back to created_at",
            stripped,
        )
        return None

    # Unexpected type
    logger.warning("normalize_date: unexpected type %s for value %r", type(value).__name__, value)
    return None