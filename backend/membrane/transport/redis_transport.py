"""RedisTransport — Redis Streams + Pub/Sub implementation of MessageTransport.

Uses XADD/XREADGROUP/XACK for stream channels and PUBLISH for advisory Pub/Sub.
Idempotency is enforced via a Redis SET keyed `membrane:seen:<channel>:<signal_id>`
with a 24-hour TTL.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .base import HealthStatus, MessageTransport, ReceivedMessage
from .channels import ALL_STREAM_CHANNELS, Channel, PUBSUB_CHANNELS
from .redis_client import get_redis_client


_SEEN_TTL_SECS = 24 * 3600
_SEEN_PREFIX = "membrane:seen"


class RedisTransport(MessageTransport):
    backend_name = "redis"

    def __init__(self) -> None:
        self._client = None

    def _r(self) -> Any:
        if self._client is None:
            self._client = get_redis_client()
        return self._client

    @staticmethod
    def _encode(payload: Dict[str, Any]) -> Dict[str, str]:
        return {"data": json.dumps(payload, default=str)}

    @staticmethod
    def _decode(fields: Dict[str, Any]) -> Dict[str, Any]:
        raw = fields.get("data") if isinstance(fields, dict) else None
        if raw is None:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw}

    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        if channel not in ALL_STREAM_CHANNELS and channel != Channel.INFRA_DEAD_LETTER:
            raise ValueError(f"channel {channel!r} is not a stream channel")
        r = self._r()
        signal_id = payload.get("signal_id")
        if isinstance(signal_id, int):
            key = f"{_SEEN_PREFIX}:{channel}:{signal_id}"
            was_new = await r.set(key, "1", ex=_SEEN_TTL_SECS, nx=True)
            if not was_new:
                return "duplicate"
        last_err: Exception = RuntimeError("not attempted")
        for _ in range(2):
            try:
                return await r.xadd(channel, self._encode(payload))
            except Exception as exc:
                last_err = exc
        # terminal failure -> DLQ + raise
        await self.dead_letter(channel, payload, f"publish_failed: {last_err!r}")
        raise last_err

    async def broadcast(self, channel: str, payload: Dict[str, Any]) -> None:
        if channel not in PUBSUB_CHANNELS:
            raise ValueError(f"channel {channel!r} is not a pubsub channel")
        await self._r().publish(channel, json.dumps(payload, default=str))

    async def ensure_group(self, channel: str, group: str) -> None:
        r = self._r()
        try:
            await r.xgroup_create(name=channel, groupname=group, id="0", mkstream=True)
        except Exception as exc:  # BUSYGROUP if already exists
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_batch(
        self,
        channel: str,
        group: str,
        consumer: str,
        *,
        count: int = 16,
        block_ms: int = 1000,
    ) -> List[ReceivedMessage]:
        r = self._r()
        await self.ensure_group(channel, group)
        resp = await r.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={channel: ">"},
            count=count,
            block=block_ms,
        )
        out: List[ReceivedMessage] = []
        if not resp:
            return out
        # resp = [(stream_name, [(id, {fields}), ...])]
        for _stream, entries in resp:
            for delivery_id, fields in entries:
                payload = self._decode(fields)
                out.append(
                    ReceivedMessage(
                        channel=channel,
                        delivery_id=delivery_id,
                        payload=payload,
                        signal_id=payload.get("signal_id") if isinstance(payload.get("signal_id"), int) else None,
                        event_id=payload.get("event_id") if isinstance(payload.get("event_id"), str) else None,
                    )
                )
        return out

    async def ack(self, channel: str, group: str, delivery_id: str) -> None:
        await self._r().xack(channel, group, delivery_id)

    async def nack(self, channel: str, group: str, delivery_id: str) -> None:
        # Redis Streams: leave un-ack'd → pending entry list, XCLAIM later.
        # Here we explicitly do nothing so the message remains pending.
        return None

    async def dead_letter(
        self, original_channel: str, payload: Dict[str, Any], reason: str
    ) -> str:
        entry = {"original_channel": original_channel, "payload": payload, "reason": reason}
        try:
            return await self._r().xadd(Channel.INFRA_DEAD_LETTER, self._encode(entry))
        except Exception:
            return "dead-letter-failed"

    async def health(self) -> HealthStatus:
        try:
            pong = await self._r().ping()
            return HealthStatus(healthy=bool(pong), backend=self.backend_name, detail="ping ok" if pong else "no pong")
        except Exception as exc:
            return HealthStatus(healthy=False, backend=self.backend_name, detail=f"{exc!r}")

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


__all__ = ["RedisTransport"]
