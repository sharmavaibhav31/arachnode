from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage

from scheduler.providers.base import NotificationEvent, NotificationProvider


class EmailProvider(NotificationProvider):
    def __init__(self) -> None:
        self.from_address = os.environ.get("GMAIL_ADDRESS", "").strip()
        self.app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
        self.to_address = os.environ.get("NOTIFICATION_EMAIL", "").strip()
        self.your_name = os.environ.get("YOUR_NAME", "Arachnode").strip()

    def validate_config(self) -> bool:
        return bool(self.from_address and self.app_password and self.to_address)

    async def send(self, event: NotificationEvent) -> bool:
        if not self.validate_config():
            return False

        subject = f"[Arachnode] {event.title}"

        parts = [event.message]
        if event.fields:
            parts.append("")
            parts.extend(f"{k}: {v}" for k, v in event.fields.items())
        body = "\n".join(parts)

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._send_sync, subject, body)
            return True
        except Exception:
            return False

    def _send_sync(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = f"{self.your_name} <{self.from_address}>"
        msg["To"] = self.to_address
        msg["Subject"] = subject
        msg.set_content(body)

        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as smtp:
            smtp.login(self.from_address, self.app_password)
            smtp.send_message(msg)
