from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class NotificationEvent:
    event_type: str
    title: str
    message: str
    fields: dict[str, Any] | None = None
    severity: str = "info"


class NotificationProvider(ABC):
    @abstractmethod
    async def send(self, event: NotificationEvent) -> bool:
        ...

    @abstractmethod
    def validate_config(self) -> bool:
        ...
