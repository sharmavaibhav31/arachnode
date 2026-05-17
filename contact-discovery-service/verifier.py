"""
verifier.py — SMTP-based email verification with per-domain rate limiting.

How it works:
  1. Look up the MX record for the domain (using dnspython or a stdlib fallback).
  2. Open an SMTP connection to the MX host.
  3. Send EHLO + MAIL FROM + RCPT TO to check if the mailbox exists.
  4. Close without DATA — no email is ever sent.

Rate limiting:
  To avoid being blocklisted, we allow a maximum of 3 verification attempts
  per domain per hour.  A simple in-memory dict tracks this; for multi-process
  deployments swap it for a Redis counter.

Verification results:
  'verified'   — SMTP server returned 250 (mailbox exists)
  'unverified' — We could not reach the MX server or it returned a 4xx
  'invalid'    — SMTP server returned 550 / 551 (mailbox does not exist)

⚠ Some large providers (Google, Microsoft) block SMTP verification and always
  return 250. Treat 'verified' as a best-effort signal, not a guarantee.
"""

from __future__ import annotations

import os
import asyncio
import logging
import smtplib
import socket
import time
from collections import defaultdict
from typing import Literal
from redis.asyncio import Redis, RedisError

logger = logging.getLogger(__name__)

VerifyResult = Literal["verified", "unverified", "invalid"]

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# One connection pool shared across all coroutines in this process.
_redis: Redis = Redis.from_url(
    REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)
 
# Key prefixes — easy to namespace if you share a Redis instance.
_KEY_CACHE = "verifier:result:"    # verifier:result:<email>
_KEY_RATE  = "verifier:rate:"      # verifier:rate:<domain>

# Per-domain rate limit: (count, window_start)
_domain_rate: dict[str, tuple[int, float]] = defaultdict(lambda: (0, time.time()))
_MAX_PER_DOMAIN_PER_HOUR = int(os.getenv("VERIFIER_MAX_PER_DOMAIN_PER_HOUR", "3"))
_WINDOW_SECONDS = int(os.getenv("VERIFIER_WINDOW_SECONDS", "3600"))
_SMTP_TIMEOUT = int(os.getenv("VERIFIER_SMTP_TIMEOUT", "5"))
_CACHE_TTL_SECONDS = int(os.getenv("VERIFIER_CACHE_TTL_SECONDS", "86400"))
# ---------------------------------------------------------------------------
# Default blocklist – providers known to fake or block SMTP verification
# ---------------------------------------------------------------------------
# Grouped by vendor so additions stay readable and reviewable.
_PROVIDER_BLOCKLIST: dict[str, set[str]] = {
    "google":    {"gmail.com", "googlemail.com"},
    "microsoft": {"outlook.com", "hotmail.com", "live.com", "msn.com", "passport.com"},
    "yahoo":     {"yahoo.com", "yahoo.co.uk", "yahoo.co.in", "ymail.com"},
    "apple":     {"icloud.com", "me.com", "mac.com"},
    "misc":      {
        "protonmail.com", "proton.me", "zoho.com", "aol.com",
        "fastmail.com", "fastmail.fm", "hey.com",
        "tutanota.com", "tutanota.de",
    },
}

_DEFAULT_BLOCKLIST: frozenset[str] = frozenset(
    domain for domains in _PROVIDER_BLOCKLIST.values() for domain in domains
)

# ---------------------------------------------------------------------------
# Environment-based extension
# ---------------------------------------------------------------------------
# Set VERIFIER_SMTP_BLOCKLIST_EXTENDS to a comma-separated list of extra
# domains that should be treated the same as the built-ins, e.g.:
#   VERIFIER_SMTP_BLOCKLIST_EXTENDS=example.com,disposable.net
# ---------------------------------------------------------------------------
def _load_env_blocklist(env_var: str = "VERIFIER_SMTP_BLOCKLIST_EXTENDS") -> frozenset[str]:
    raw = os.getenv(env_var, "")
    return frozenset(d.strip().lower() for d in raw.split(",") if d.strip())


def build_smtp_blocklist(
    *,
    extra_domains: frozenset[str] | set[str] | None = None,
    env_var: str = "VERIFIER_SMTP_BLOCKLIST_EXTENDS",
) -> frozenset[str]:
    """
    Compose the final SMTP blocklist from three sources (lowest → highest priority):

    1. ``_DEFAULT_BLOCKLIST``  – the hardcoded vendor groups above.
    2. ``VERIFIER_SMTP_BLOCKLIST_EXTENDS`` env var – ops/infra overrides at deploy time.
    3. ``extra_domains`` kwarg – programmatic overrides from calling code or tests.
    """
    env_domains = _load_env_blocklist(env_var)
    caller_domains = frozenset(d.lower() for d in (extra_domains or set()))
    return _DEFAULT_BLOCKLIST | env_domains | caller_domains


# Module-level singleton – used by default; callers can build their own.
SMTP_BLOCKLIST: frozenset[str] = build_smtp_blocklist()

async def _cache_get(email: str) -> VerifyResult | None:
    """Return the cached result for *email*, or None on miss / Redis error."""
    try:
        value = await _redis.get(f"{_KEY_CACHE}{email}")
        if value is not None:
            logger.debug("[Verifier] Cache hit for %s → %s", email, value)
            return value  # type: ignore[return-value]
        return None
    except RedisError as exc:
        logger.warning("[Verifier] Redis cache GET failed: %s", exc)
        return None
 
 
async def _cache_set(email: str, result: VerifyResult) -> None:
    """Persist a definitive result in Redis.  'unverified' is never cached."""
    if result == "unverified":
        return
    try:
        await _redis.set(f"{_KEY_CACHE}{email}", result, ex=_CACHE_TTL_SECONDS)
    except RedisError as exc:
        logger.warning("[Verifier] Redis cache SET failed: %s", exc)


async def _rate_check_and_increment(domain: str) -> bool:
    """
    Atomically increment the per-domain counter and return True if the request
    is within quota, False if the limit has been reached.
 
    Uses the standard INCR + EXPIRE pattern
    """
    key = f"{_KEY_RATE}{domain}"
    try:
        count = await _redis.incr(key)
        if count == 1:
            # First probe in this window — set the expiry.
            await _redis.expire(key, _WINDOW_SECONDS)
        if count > _MAX_PER_DOMAIN_PER_HOUR:
            logger.warning(
                "[Verifier] Rate limit reached for domain '%s' (%d/hr). Skipping.",
                domain,
                _MAX_PER_DOMAIN_PER_HOUR,
            )
            # Roll back the increment so we don't over-count.
            await _redis.decr(key)
            return False
        return True
    except RedisError as exc:
        # If Redis is down, fail open so legitimate checks aren't silently dropped.
        logger.warning("[Verifier] Redis rate-limit check failed, failing open: %s", exc)
        return True



def _resolve_mx(domain: str) -> str | None:
    """
    Return the highest-priority MX hostname for *domain*, or None if not found.
    Uses dnspython when available, falls back to a socket probe of the domain itself.
    """
    try:
        import dns.resolver  # type: ignore
        answers = dns.resolver.resolve(domain, "MX")
        # sort by preference (lowest = highest priority)
        mx_host = sorted(answers, key=lambda r: r.preference)[0].exchange.to_text().rstrip(".")
        return mx_host
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("[Verifier] dnspython MX lookup failed for %s: %s", domain, exc)

    # Fallback: assume domain itself accepts SMTP (works for many companies)
    return f"mail.{domain}"


def _smtp_check_sync(email: str, mx_host: str) -> VerifyResult:
    """
    Synchronous SMTP check (run in a thread-pool executor).
    Returns the verification result string.
    """
    from_addr = "noreply@jobdiscovery.internal"
    try:
        with smtplib.SMTP(timeout=_SMTP_TIMEOUT) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo("jobdiscovery.internal")
            smtp.mail(from_addr)
            code, _ = smtp.rcpt(email)
            if code == 250:
                return "verified"
            elif code in (550, 551, 553):
                return "invalid"
            else:
                return "unverified"
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
            socket.timeout, ConnectionRefusedError, OSError) as exc:
        logger.debug("[Verifier] SMTP connect failed for %s via %s: %s", email, mx_host, exc)
        return "unverified"
    except Exception as exc:
        logger.debug("[Verifier] Unexpected SMTP error for %s: %s", email, exc)
        return "unverified"


async def verify_email(email: str) -> VerifyResult:
    """
    Async wrapper around the SMTP check.
    Enforces per-domain rate limiting before connecting.
    Returns 'unverified' immediately if rate limit is exceeded.
    """
    if not email or "@" not in email:
        return "invalid"

    domain = email.split("@", 1)[1].lower()

    # 1. Cache look-up
    cached = await _cache_get(email)
    if cached is not None:
        return cached
 
    # 2. Blocklist check
    if domain in SMTP_BLOCKLIST:
        logger.info("[Verifier] %s is on the SMTP blocklist — skipping probe.", domain)
        return "unverified"
 
    # 3. Rate limit (atomic check-and-increment)
    if not await _rate_check_and_increment(domain):
        return "unverified"


    mx_host = _resolve_mx(domain)
    if not mx_host:
        logger.debug("[Verifier] No MX record found for %s", domain)
        return "unverified"

    loop = asyncio.get_running_loop()
    result: VerifyResult = await loop.run_in_executor(
        None, _smtp_check_sync, email, mx_host
    )
    logger.info("[Verifier] %s → %s (via %s)", email, result, mx_host)

    await _cache_set(email, result)

    return result
