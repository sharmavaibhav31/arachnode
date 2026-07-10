from __future__ import annotations

import os

import httpx

from scheduler.providers.base import NotificationEvent, NotificationProvider


class DiscordProvider(NotificationProvider):
    def __init__(self) -> None:
        self.webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        self._client: httpx.AsyncClient | None = None

    def validate_config(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, event: NotificationEvent) -> bool:
        if not self.validate_config():
            return False

        color_map = {"info": 0x4F9EFF, "warning": 0xF59E0B, "error": 0xEF4444, "success": 0x22C55E}

        embed = {
            "title": event.title,
            "description": event.message,
            "color": color_map.get(event.severity, 0x4F9EFF),
            "footer": {"text": f"{event.event_type} · severity: {event.severity}"},
        }

        if event.fields:
            embed["fields"] = [{"name": k, "value": str(v), "inline": True} for k, v in event.fields.items()]

        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            return True
        except Exception:
            return False
