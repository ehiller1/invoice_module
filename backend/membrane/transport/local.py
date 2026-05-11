"""LocalTransport — in-process MessageTransport for tests and dev.

Uses asyncio.Queue per (channel, group) with simple sequence-id delivery
identifiers. Supports idempotency dedup keyed on `signal_id`.
"""
from __future__ import annotations

import asyncio
import itertools
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from .base import HealthStatus, MessageTransport, ReceivedMessage
from .channels import ALL_STREAM_CHANNELS, Channel, PUBSUB_CHANNELS


class LocalTransport(MessageTransport):
    backend_name = "local"

    def __init__(self) -> None:
        # group queues: (channel, group) -> asyncio.Queue[ReceivedMessage]
        self._group_queues: Dict[Tuple[str, str], asyncio.Queue] = {}
        # channel -> list of groups so publish fans out
        self._groups_by_channel: Dict[str, Set[str]] = defaultdict(set)
        # pubsub subscribers (channel -> list of asyncio.Queue)
        self._pubsub: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        # idempotency set: (channel, signal_id) already delivered
        self._seen: Set[Tuple[str, int]] = set()
        # in-flight messages by delivery_id for nack/redelivery
        self._inflight: Dict[str, ReceivedMessage] = {}
        self._counter = itertools.count(1)
        # dead-letter queue (also visible as a normal stream channel)
        self._dead_letter: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def _next_id(self) -> str:
        return f"local-{next(self._counter)}"

    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        if channel not in ALL_STREAM_CHANNELS and channel != Channel.INFRA_DEAD_LETTER:
            raise ValueError(f"channel {channel!r} is not a stream channel")
        signal_id = payload.get("signal_id")
        event_id = payload.get("event_id")
        async with self._lock:
            # idempotency: drop duplicate signal_id on same channel
            if isinstance(signal_id, int):
                key = (channel, signal_id)
                if key in self._seen:
                    return "duplicate"
                self._seen.add(key)
            delivery_id = self._next_id()
            groups = list(self._groups_by_channel.get(channel, ()))
            for group in groups:
                msg = ReceivedMessage(
                    channel=channel,
                    delivery_id=f"{delivery_id}:{group}",
                    payload=dict(payload),
                    signal_id=signal_id if isinstance(signal_id, int) else None,
                    event_id=event_id if isinstance(event_id, str) else None,
                )
                self._inflight[msg.delivery_id] = msg
                self._group_queues[(channel, group)].put_nowait(msg)
        return delivery_id

    async def broadcast(self, channel: str, payload: Dict[str, Any]) -> None:
        if channel not in PUBSUB_CHANNELS:
            raise ValueError(f"channel {channel!r} is not a pubsub channel")
        for q in list(self._pubsub.get(channel, [])):
            q.put_nowait(dict(payload))

    async def ensure_group(self, channel: str, group: str) -> None:
        async with self._lock:
            self._groups_by_channel[channel].add(group)
            self._group_queues.setdefault((channel, group), asyncio.Queue())

    async def consume_batch(
        self,
        channel: str,
        group: str,
        consumer: str,
        *,
        count: int = 16,
        block_ms: int = 1000,
    ) -> List[ReceivedMessage]:
        await self.ensure_group(channel, group)
        q = self._group_queues[(channel, group)]
        out: List[ReceivedMessage] = []
        timeout = max(block_ms, 0) / 1000.0
        try:
            first = await asyncio.wait_for(q.get(), timeout=timeout) if timeout > 0 else q.get_nowait()
            out.append(first)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return out
        while len(out) < count:
            try:
                out.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def ack(self, channel: str, group: str, delivery_id: str) -> None:
        self._inflight.pop(delivery_id, None)

    async def nack(self, channel: str, group: str, delivery_id: str) -> None:
        msg = self._inflight.pop(delivery_id, None)
        if msg is not None:
            self._group_queues[(channel, group)].put_nowait(msg)
            self._inflight[delivery_id] = msg

    async def dead_letter(
        self, original_channel: str, payload: Dict[str, Any], reason: str
    ) -> str:
        entry = {"original_channel": original_channel, "payload": dict(payload), "reason": reason}
        self._dead_letter.append(entry)
        # also fan-out to subscribers of INFRA_DEAD_LETTER if any
        async with self._lock:
            delivery_id = self._next_id()
            for group in list(self._groups_by_channel.get(Channel.INFRA_DEAD_LETTER, ())):
                msg = ReceivedMessage(
                    channel=Channel.INFRA_DEAD_LETTER,
                    delivery_id=f"{delivery_id}:{group}",
                    payload=entry,
                )
                self._inflight[msg.delivery_id] = msg
                self._group_queues[(Channel.INFRA_DEAD_LETTER, group)].put_nowait(msg)
        return delivery_id

    async def health(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            backend=self.backend_name,
            detail=f"channels={len(self._groups_by_channel)} inflight={len(self._inflight)}",
        )

    # ---- test helpers ----
    def dead_letters(self) -> List[Dict[str, Any]]:
        return list(self._dead_letter)

    def subscribe_pubsub(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._pubsub[channel].append(q)
        return q

    def reset(self) -> None:
        self._group_queues.clear()
        self._groups_by_channel.clear()
        self._pubsub.clear()
        self._seen.clear()
        self._inflight.clear()
        self._dead_letter.clear()


__all__ = ["LocalTransport"]
