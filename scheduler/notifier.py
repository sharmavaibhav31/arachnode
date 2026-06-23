"""
notifier.py — Webhook & notification dispatcher for the Scheduler Service.

Keeps notification delivery isolated from core scheduler flow:
  - All provider calls are wrapped in try/except — failures never
    propagate to the caller (fire-and-forget with logging).
  - Rate limiting prevents spam: at most 1 notification per event type
    per RATE_LIMIT_WINDOW_SECS (default 300 s = 5 min).
  - Provider registration is modular — add a new channel by subclassing
    NotificationProvider and registering it with Notifier.register().

Usage:
    from notifier import notifier
    await notifier.dispatch("jobs:new", title="...", message="...", fields={...})
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from logger import get_logger
from providers import (
    DiscordProvider,
    EmailProvider,
    NotificationEvent,
    NotificationProvider,
    SlackProvider,
)

log = get_logger("scheduler.notifier")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RATE_LIMIT_WINDOW_SECS = int(os.environ.get("NOTIFY_RATE_LIMIT_SECS", "300"))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_providers: list[NotificationProvider] = []
_last_sent: dict[str, float] = {}       # event_type → timestamp
_enabled_events: set[str] = set()       # empty = all enabled


def register(provider: NotificationProvider) -> None:
    """Register a notification provider."""
    if provider.validate_config():
        _providers.append(provider)
        log.info("Provider registered", provider=type(provider).__name__)


def configure(event_types: list[str] | None = None) -> None:
    """Set which event types are enabled. None = all enabled."""
    global _enabled_events
    if event_types is None:
        _enabled_events = set()
    else:
        _enabled_events = set(event_types)


def _is_enabled(event_type: str) -> bool:
    return not _enabled_events or event_type in _enabled_events


def _is_rate_limited(event_type: str) -> bool:
    now = time.time()
    last = _last_sent.get(event_type, 0.0)
    if now - last < RATE_LIMIT_WINDOW_SECS:
        remaining = int(RATE_LIMIT_WINDOW_SECS - (now - last))
        log.debug("Rate-limited", event_type=event_type, remaining_secs=remaining)
        return True
    _last_sent[event_type] = now
    return False


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def dispatch(
    event_type: str,
    title: str,
    message: str,
    fields: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    """
    Fire a notification event to all configured providers.

    This function is intentionally fire-and-forget from the caller's
    perspective — exceptions inside providers are caught and logged,
    never propagated.
    """
    if not _is_enabled(event_type):
        log.debug("Event type disabled, skipping", event_type=event_type)
        return

    if _is_rate_limited(event_type):
        return

    if not _providers:
        log.debug("No providers configured, skipping notification", event_type=event_type)
        return

    event = NotificationEvent(
        event_type=event_type,
        title=title,
        message=message,
        fields=fields,
        severity=severity,
    )

    results = await asyncio.gather(
        *(p.send(event) for p in _providers),
        return_exceptions=True,
    )

    for provider, result in zip(_providers, results):
        pname = type(provider).__name__
        if isinstance(result, Exception):
            log.error("Provider send failed", provider=pname, error=str(result))
        elif not result:
            log.warning("Provider returned failure", provider=pname)
        else:
            log.info("Notification sent", provider=pname, event_type=event_type)


# ---------------------------------------------------------------------------
# Sync wrapper (for APScheduler thread-pool usage)
# ---------------------------------------------------------------------------

def dispatch_sync(
    event_type: str,
    title: str,
    message: str,
    fields: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    """Synchronous wrapper for use in APScheduler thread-pool jobs."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        asyncio.ensure_future(dispatch(event_type, title, message, fields, severity))
    else:
        asyncio.run(dispatch(event_type, title, message, fields, severity))


# ---------------------------------------------------------------------------
# Init: auto-register providers from env
# ---------------------------------------------------------------------------

def init_from_env() -> None:
    """Read env vars and register the providers that are configured."""
    slack = SlackProvider()
    if slack.validate_config():
        register(slack)

    discord = DiscordProvider()
    if discord.validate_config():
        register(discord)

    email = EmailProvider()
    if email.validate_config():
        register(email)

    if not _providers:
        log.info("No notification providers configured — all notifications will be no-ops.")
    else:
        log.info("Notification system initialized", provider_count=len(_providers))


# ---------------------------------------------------------------------------
# Singleton notifier instance
# ---------------------------------------------------------------------------

notifier = dispatch_sync

# Auto-init on import
init_from_env()
