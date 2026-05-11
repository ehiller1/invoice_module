"""EventQueryTransport — abstract interface for event history queries."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    channel: str
    occurred_at: datetime
    payload: Dict[str, Any] = field(default_factory=dict)
    signal_id: Optional[int] = None
    correlation_id: Optional[str] = None


@dataclass(frozen=True)
class QueryFilter:
    channel: Optional[str] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    correlation_id: Optional[str] = None
    signal_name: Optional[str] = None
    limit: int = 100


@dataclass(frozen=True)
class QueryHealth:
    healthy: bool
    backend: str
    detail: str = ""


class EventQueryTransport(ABC):
    """Query historical events recorded on the membrane."""

    backend_name: str = "abstract"

    @abstractmethod
    async def record(self, event: EventRecord) -> None:
        """Index an event for later query (write side)."""

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[EventRecord]:
        """Lookup by primary event_id."""

    @abstractmethod
    async def query(self, q: QueryFilter) -> List[EventRecord]:
        """Range/filter query."""

    @abstractmethod
    async def search(self, text: str, *, limit: int = 20) -> List[EventRecord]:
        """Full-text search over payloads."""

    @abstractmethod
    async def health(self) -> QueryHealth:
        ...

    async def close(self) -> None:  # pragma: no cover — optional
        return None


__all__ = ["EventQueryTransport", "EventRecord", "QueryFilter", "QueryHealth"]
