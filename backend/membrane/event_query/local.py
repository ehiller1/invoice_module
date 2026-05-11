"""LocalEventQuery — in-memory index for tests/dev."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .base import EventQueryTransport, EventRecord, QueryFilter, QueryHealth


class LocalEventQuery(EventQueryTransport):
    backend_name = "local"

    def __init__(self) -> None:
        self._by_id: Dict[str, EventRecord] = {}
        self._all: List[EventRecord] = []

    async def record(self, event: EventRecord) -> None:
        self._by_id[event.event_id] = event
        self._all.append(event)

    async def get_event(self, event_id: str) -> Optional[EventRecord]:
        return self._by_id.get(event_id)

    async def query(self, q: QueryFilter) -> List[EventRecord]:
        out: List[EventRecord] = []
        for ev in self._all:
            if q.channel and ev.channel != q.channel:
                continue
            if q.since and ev.occurred_at < q.since:
                continue
            if q.until and ev.occurred_at > q.until:
                continue
            if q.correlation_id and ev.correlation_id != q.correlation_id:
                continue
            if q.signal_name and ev.payload.get("signal_name") != q.signal_name:
                continue
            out.append(ev)
            if len(out) >= q.limit:
                break
        return out

    async def search(self, text: str, *, limit: int = 20) -> List[EventRecord]:
        needle = text.lower()
        out: List[EventRecord] = []
        for ev in self._all:
            hay = json.dumps(ev.payload, default=str).lower()
            if needle in hay or needle in ev.channel.lower() or needle in ev.event_id.lower():
                out.append(ev)
                if len(out) >= limit:
                    break
        return out

    async def health(self) -> QueryHealth:
        return QueryHealth(healthy=True, backend=self.backend_name, detail=f"events={len(self._all)}")

    def reset(self) -> None:
        self._by_id.clear()
        self._all.clear()


__all__ = ["LocalEventQuery"]
