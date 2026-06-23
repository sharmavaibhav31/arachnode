"""
verifier.py — SMTP-based email verification with per-domain rate limiting using Redis.
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
import os
import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Lightweight and robust regex for validating basic email structure:
# - Exactly one "@"
# - Non-empty local part
# - Non-empty domain with a valid domain-like structure (e.g. domain.tld)
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

VerifyResult = Literal["verified", "unverified", "invalid"]

_SMTP_TIMEOUT = 5   # seconds

# Set up global redis client
REDIS_URL = f"redis://{os.environ.get('REDIS_HOST', 'redis')}:{os.environ.get('REDIS_PORT', '6379')}"
try:
    global_redis = redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    global_redis = None

async def _check_rate_limit(domain: str, redis_client) -> bool:
    """
    Returns True if the domain is within rate limit.
    Max 3 SMTP verifications per domain per hour.
    """
    if redis_client is None:
        logger.warning("[Verifier] Redis client is None. Failing open for rate limit.")
        return True

    try:
        key = f"smtp_rate:{domain}"
        count = await redis_client.get(key)
        
        if count is None:
            await redis_client.setex(key, 3600, 1)
            return True
        
        if int(count) >= 3:
            logger.warning("[Verifier] Rate limit reached for domain '%s' (3/hr). Skipping.", domain)
            return False
        
        await redis_client.incr(key)
        return True
    except Exception as e:
        logger.warning(f"[Verifier] Redis rate limit check failed: {e}. Failing open.")
        return True


def _resolve_mx(domain: str) -> str | None:
    try:
        import dns.resolver  # type: ignore
        answers = dns.resolver.resolve(domain, "MX")
        mx_host = sorted(answers, key=lambda r: r.preference)[0].exchange.to_text().rstrip(".")
        return mx_host
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("[Verifier] dnspython MX lookup failed for %s: %s", domain, exc)

    return f"mail.{domain}"


def _smtp_check_sync(email: str, mx_host: str) -> VerifyResult:
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


async def verify_email(email: str, redis_client=None) -> VerifyResult:
    """
    Async wrapper around the SMTP check.
    Enforces per-domain rate limiting using Redis before connecting.
    """
    if not email or not EMAIL_REGEX.match(email):
        return "invalid"

    domain = email.split("@", 1)[1].lower()
    
    # Use global_redis if none provided (e.g. from discovery.py)
    rc = redis_client if redis_client is not None else global_redis

    allowed = await _check_rate_limit(domain, rc)
    if not allowed:
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
    return result
