"""Consumer base class — consumer-group semantics + idempotency dedup.

Subclasses override `handle(message)`. The base class:
  - Ensures the consumer group exists.
  - Reads a batch via the transport.
  - Skips messages whose `signal_id` has already been processed.
  - Acks on success, nacks (or DLQs after max retries) on failure.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Set, Tuple

from .base import MessageTransport, ReceivedMessage


class Consumer:
    max_retries: int = 3

    def __init__(
        self,
        transport: MessageTransport,
        channel: str,
        group: str,
        consumer_name: str,
    ) -> None:
        self.transport = transport
        self.channel = channel
        self.group = group
        self.consumer_name = consumer_name
        self._processed: Set[Tuple[str, int]] = set()
        self._attempts: dict[str, int] = {}
        self._stop = asyncio.Event()

    async def handle(self, message: ReceivedMessage) -> None:  # pragma: no cover — override
        raise NotImplementedError

    def _is_duplicate(self, msg: ReceivedMessage) -> bool:
        if msg.signal_id is None:
            return False
        key = (msg.channel, msg.signal_id)
        # Already-processed only counts once handle() succeeds; we mark in
        # step() after a successful handle, so retries are not flagged here.
        return key in self._processed

    def _mark_processed(self, msg: ReceivedMessage) -> None:
        if msg.signal_id is not None:
            self._processed.add((msg.channel, msg.signal_id))

    async def step(self, *, block_ms: int = 1000, count: int = 16) -> int:
        await self.transport.ensure_group(self.channel, self.group)
        batch = await self.transport.consume_batch(
            self.channel, self.group, self.consumer_name, count=count, block_ms=block_ms
        )
        for msg in batch:
            if self._is_duplicate(msg):
                await self.transport.ack(self.channel, self.group, msg.delivery_id)
                continue
            try:
                await self.handle(msg)
                self._mark_processed(msg)
                await self.transport.ack(self.channel, self.group, msg.delivery_id)
                self._attempts.pop(msg.delivery_id, None)
            except Exception as exc:
                attempts = self._attempts.get(msg.delivery_id, 0) + 1
                self._attempts[msg.delivery_id] = attempts
                if attempts >= self.max_retries:
                    await self.transport.dead_letter(
                        msg.channel, msg.payload, f"max_retries_exceeded: {exc!r}"
                    )
                    await self.transport.ack(self.channel, self.group, msg.delivery_id)
                    self._attempts.pop(msg.delivery_id, None)
                else:
                    await self.transport.nack(self.channel, self.group, msg.delivery_id)
        return len(batch)

    async def run(self, *, block_ms: int = 1000) -> None:
        while not self._stop.is_set():
            try:
                await self.step(block_ms=block_ms)
            except Exception:
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._stop.set()


__all__ = ["Consumer"]
