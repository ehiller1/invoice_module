"""EmbarkEventQuery — stub for the future Embark platform query service."""
from __future__ import annotations

import os
from typing import List, Optional

from .base import EventQueryTransport, EventRecord, QueryFilter, QueryHealth


class EmbarkEventQuery(EventQueryTransport):
    backend_name = "platform"

    def __init__(self) -> None:
        self.query_url = os.environ.get("PLATFORM_QUERY_URL", "")

    def _ni(self, op: str) -> NotImplementedError:
        return NotImplementedError(
            f"EmbarkEventQuery.{op} is a stub; set PLATFORM_QUERY_URL and "
            f"implement the Embark query adapter to use EVENT_QUERY_BACKEND=platform"
        )

    async def record(self, event: EventRecord) -> None:
        raise self._ni("record")

    async def get_event(self, event_id: str) -> Optional[EventRecord]:
        raise self._ni("get_event")

    async def query(self, q: QueryFilter) -> List[EventRecord]:
        raise self._ni("query")

    async def search(self, text: str, *, limit: int = 20) -> List[EventRecord]:
        raise self._ni("search")

    async def health(self) -> QueryHealth:
        return QueryHealth(
            healthy=False,
            backend=self.backend_name,
            detail=("stub: PLATFORM_QUERY_URL=" + (self.query_url or "<unset>")),
        )


__all__ = ["EmbarkEventQuery"]
