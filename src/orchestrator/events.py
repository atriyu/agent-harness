"""Simple event bus for inter-agent communication and logging.

Provides a lightweight pub/sub mechanism for pipeline events such as
stage transitions, warnings, and progress updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PipelineEvent:
    event_type: str  # e.g. "stage_started", "stage_completed", "budget_warning"
    stage: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


EventHandler = Callable[[PipelineEvent], None]


class EventBus:
    """Simple synchronous event bus for pipeline lifecycle events."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}

    def on(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: PipelineEvent) -> None:
        logger.debug("Event: %s stage=%s", event.event_type, event.stage)
        for handler in self._handlers.get(event.event_type, []):
            handler(event)
        # Also fire wildcard handlers
        for handler in self._handlers.get("*", []):
            handler(event)
