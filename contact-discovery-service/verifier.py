"""
verifier.py — SMTP-based email verification with per-domain rate limiting.

How it works:
  1. Look up the MX record for the domain (using dnspython or a stdlib fallback).
  2. Open an SMTP connection to the MX host.
  3. Send EHLO + MAIL FROM + RCPT TO to check if the mailbox exists.
  4. Close without DATA — no email is ever sent.

Rate limiting:
  To avoid being blocklisted, we allow a maximum of 5 verification attempts
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

import asyncio
import logging
import re
import smtplib
import socket
import time
from collections import defaultdict
from typing import Literal

logger = logging.getLogger(__name__)

# Lightweight and robust regex for validating basic email structure:
# - Exactly one "@"
# - Non-empty local part
# - Non-empty domain with a valid domain-like structure (e.g. domain.tld)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

VerifyResult = Literal["verified", "unverified", "invalid"]

# Per-domain rate limit: (count, window_start)
_domain_rate: dict[str, tuple[int, float]] = defaultdict(lambda: (0, time.time()))
_MAX_PER_DOMAIN_PER_HOUR = 5
_WINDOW_SECONDS = 3600
_SMTP_TIMEOUT = 5   # seconds


def _rate_allowed(domain: str) -> bool:
    """Return True if we have quota left for this domain this hour."""
    count, window_start = _domain_rate[domain]
    now = time.time()
    if now - window_start > _WINDOW_SECONDS:
        # Window expired — reset
        _domain_rate[domain] = (0, now)
        return True
    if count >= _MAX_PER_DOMAIN_PER_HOUR:
        logger.warning(
            "[Verifier] Rate limit reached for domain '%s' (%d/hr). Skipping.",
            domain, _MAX_PER_DOMAIN_PER_HOUR,
        )
        return False
    return True


def _increment_rate(domain: str) -> None:
    count, window_start = _domain_rate[domain]
    _domain_rate[domain] = (count + 1, window_start)


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
    if not email or not EMAIL_REGEX.match(email):
        return "invalid"

    domain = email.split("@", 1)[1].lower()

    if not _rate_allowed(domain):
        return "unverified"

    mx_host = _resolve_mx(domain)
    if not mx_host:
        logger.debug("[Verifier] No MX record found for %s", domain)
        return "unverified"

    _increment_rate(domain)
    loop = asyncio.get_running_loop()
    result: VerifyResult = await loop.run_in_executor(
        None, _smtp_check_sync, email, mx_host
    )
    logger.info("[Verifier] %s → %s (via %s)", email, result, mx_host)
    return result
