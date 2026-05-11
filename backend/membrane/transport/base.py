"""MessageTransport abstract interface (Phase 2).

A MessageTransport hides the difference between in-process queues (tests),
Redis Streams/Pub/Sub (production), and a future Embark platform mesh
(integration). Business logic depends only on this ABC, never on redis-py.

Semantics
---------
- `publish` is fire-and-forget with internal 2-attempt retry; on terminal
  failure the message is routed to the `infra:dead_letter` stream.
- `consume_batch` reads from a consumer group with a configurable block-ms.
- `ack` finalizes message delivery; `nack` returns it for redelivery.
- `broadcast` targets advisory Pub/Sub channels (ephemeral).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ReceivedMessage:
    """A message delivered to a consumer.

    `delivery_id` is transport-specific (Redis Stream entry ID, asyncio
    sequence, etc.) and is required for `ack` / `nack`.
    """

    channel: str
    delivery_id: str
    payload: Dict[str, Any]
    signal_id: Optional[int] = None
    event_id: Optional[str] = None


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    backend: str
    detail: str = ""


class MessageTransport(ABC):
    """Abstract message bus used by publishers and consumers."""

    backend_name: str = "abstract"

    @abstractmethod
    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        """Publish to a stream channel. Returns the delivery_id.

        On terminal failure, routes to `infra:dead_letter` and raises.
        """

    @abstractmethod
    async def broadcast(self, channel: str, payload: Dict[str, Any]) -> None:
        """Pub/Sub broadcast (no durable storage, no consumer group)."""

    @abstractmethod
    async def consume_batch(
        self,
        channel: str,
        group: str,
        consumer: str,
        *,
        count: int = 16,
        block_ms: int = 1000,
    ) -> List[ReceivedMessage]:
        """Read up to `count` messages for the consumer group."""

    @abstractmethod
    async def ack(self, channel: str, group: str, delivery_id: str) -> None:
        """Acknowledge a delivery."""

    @abstractmethod
    async def nack(self, channel: str, group: str, delivery_id: str) -> None:
        """Negative-ack: return the message for redelivery."""

    @abstractmethod
    async def ensure_group(self, channel: str, group: str) -> None:
        """Idempotently create the consumer group for a channel."""

    @abstractmethod
    async def dead_letter(
        self,
        original_channel: str,
        payload: Dict[str, Any],
        reason: str,
    ) -> str:
        """Push a failed message to `infra:dead_letter`."""

    @abstractmethod
    async def health(self) -> HealthStatus:
        """Backend health probe."""

    async def close(self) -> None:  # pragma: no cover — optional override
        """Release backend resources (override if needed)."""
        return None


__all__ = ["MessageTransport", "ReceivedMessage", "HealthStatus"]
