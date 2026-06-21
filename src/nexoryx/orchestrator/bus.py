"""Leichter in-process Pub/Sub Message Bus (Plan §6.1).

Topics mit Wildcard-Präfix (`task.*`). Subscriber bekommen Events synchron.
Für das MVP ausreichend; später auf Redis/NATS erweiterbar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Event:
    topic: str
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class Bus:
    def __init__(self) -> None:
        self._subs: list[tuple[str, Callable[[Event], None]]] = []

    def subscribe(self, prefix: str, handler: Callable[[Event], None]) -> None:
        self._subs.append((prefix, handler))

    def publish(self, topic: str, **payload) -> None:
        event = Event(topic=topic, payload=payload)
        for prefix, handler in self._subs:
            if topic == prefix or topic.startswith(prefix.rstrip("*")):
                try:
                    handler(event)
                except Exception:  # ein Subscriber darf den Bus nicht killen
                    pass
