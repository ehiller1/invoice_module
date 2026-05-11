"""RedisEventQuery — Redis Streams + sorted-set secondary index.

Indexing strategy
-----------------
- `membrane:event:<event_id>` (HASH) — primary record (JSON payload + meta).
- `membrane:idx:channel:<channel>` (ZSET, score=occurred_at_unix) — for
  channel/range scans.
- `membrane:idx:corr:<correlation_id>` (SET) — correlation grouping.
- `membrane:idx:text` (Redis Stream or RediSearch index) — full-text. The
  current implementation uses a naive scan of recent events; swap to
  RediSearch FT.SEARCH when Redis Stack is confirmed in deployment.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from ..transport.redis_client import get_redis_client
from .base import EventQueryTransport, EventRecord, QueryFilter, QueryHealth


_EVENT_KEY = "membrane:event"
_CHANNEL_IDX = "membrane:idx:channel"
_CORR_IDX = "membrane:idx:corr"
_ALL_IDX = "membrane:idx:all"  # ZSET of all events by time


class RedisEventQuery(EventQueryTransport):
    backend_name = "redis"

    def __init__(self) -> None:
        self._client = None

    def _r(self) -> Any:
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    @staticmethod
    def _ts(dt: datetime) -> float:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    async def record(self, event: EventRecord) -> None:
        r = self._r()
        key = f"{_EVENT_KEY}:{event.event_id}"
        body = {
            "event_id": event.event_id,
            "channel": event.channel,
            "occurred_at": event.occurred_at.isoformat(),
            "payload": json.dumps(event.payload, default=str),
            "signal_id": "" if event.signal_id is None else str(event.signal_id),
            "correlation_id": event.correlation_id or "",
        }
        score = self._ts(event.occurred_at)
        pipe = r.pipeline()
        pipe.hset(key, mapping=body)
        pipe.zadd(f"{_CHANNEL_IDX}:{event.channel}", {event.event_id: score})
        pipe.zadd(_ALL_IDX, {event.event_id: score})
        if event.correlation_id:
            pipe.sadd(f"{_CORR_IDX}:{event.correlation_id}", event.event_id)
        await pipe.execute()

    async def _load(self, event_id: str) -> Optional[EventRecord]:
        r = self._r()
        body = await r.hgetall(f"{_EVENT_KEY}:{event_id}")
        if not body:
            return None
        payload_raw = body.get("payload", "{}")
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {"_raw": payload_raw}
        signal_id = body.get("signal_id") or ""
        return EventRecord(
            event_id=body.get("event_id", event_id),
            channel=body.get("channel", ""),
            occurred_at=datetime.fromisoformat(body["occurred_at"]) if body.get("occurred_at") else datetime.now(timezone.utc),
            payload=payload,
            signal_id=int(signal_id) if signal_id else None,
            correlation_id=body.get("correlation_id") or None,
        )

    async def get_event(self, event_id: str) -> Optional[EventRecord]:
        return await self._load(event_id)

    async def query(self, q: QueryFilter) -> List[EventRecord]:
        r = self._r()
        lo = self._ts(q.since) if q.since else "-inf"
        hi = self._ts(q.until) if q.until else "+inf"
        if q.channel:
            zkey = f"{_CHANNEL_IDX}:{q.channel}"
        else:
            zkey = _ALL_IDX
        ids = await r.zrangebyscore(zkey, lo, hi, start=0, num=q.limit)
        out: List[EventRecord] = []
        for eid in ids:
            ev = await self._load(eid)
            if ev is None:
                continue
            if q.correlation_id and ev.correlation_id != q.correlation_id:
                continue
            if q.signal_name and ev.payload.get("signal_name") != q.signal_name:
                continue
            out.append(ev)
        return out

    async def search(self, text: str, *, limit: int = 20) -> List[EventRecord]:
        r = self._r()
        needle = text.lower()
        # naive scan over the most recent N entries; replace with RediSearch later
        ids = await r.zrevrange(_ALL_IDX, 0, 500)
        out: List[EventRecord] = []
        for eid in ids:
            ev = await self._load(eid)
            if ev is None:
                continue
            hay = json.dumps(ev.payload, default=str).lower()
            if needle in hay or needle in ev.channel.lower() or needle in ev.event_id.lower():
                out.append(ev)
                if len(out) >= limit:
                    break
        return out

    async def health(self) -> QueryHealth:
        try:
            pong = await self._r().ping()
            return QueryHealth(healthy=bool(pong), backend=self.backend_name, detail="ping ok")
        except Exception as exc:
            return QueryHealth(healthy=False, backend=self.backend_name, detail=f"{exc!r}")


__all__ = ["RedisEventQuery"]
