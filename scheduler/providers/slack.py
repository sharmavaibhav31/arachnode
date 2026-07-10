from __future__ import annotations

import os

import httpx

from scheduler.providers.base import NotificationEvent, NotificationProvider


class SlackProvider(NotificationProvider):
    def __init__(self) -> None:
        self.webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        self._client: httpx.AsyncClient | None = None

    def validate_config(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, event: NotificationEvent) -> bool:
        if not self.validate_config():
            return False

        color_map = {"info": "#4f9eff", "warning": "#f59e0b", "error": "#ef4444", "success": "#22c55e"}
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": event.title},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": event.message},
            },
        ]

        if event.fields:
            fields = [{"type": "mrkdwn", "text": f"*{k}:* {v}"} for k, v in event.fields.items()]
            blocks.append({"type": "section", "fields": fields})

        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Severity:* {event.severity}  ·  *Event:* `{event.event_type}`"}],
        })

        payload = {
            "attachments": [{
                "color": color_map.get(event.severity, "#4f9eff"),
                "blocks": blocks,
            }]
        }

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            return True
        except Exception:
            return False
