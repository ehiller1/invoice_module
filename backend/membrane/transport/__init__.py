"""Transport singleton and factory (Phase 2).

Selects the MessageTransport implementation based on TRANSPORT_BACKEND.
"""
from __future__ import annotations

import os
from typing import Optional

from .base import HealthStatus, MessageTransport, ReceivedMessage
from .channels import (
    ALL_CHANNELS,
    ALL_STREAM_CHANNELS,
    CROSS_DOMAIN_CHANNELS,
    INFRA_STREAM_CHANNELS,
    INTERNAL_STREAM_CHANNELS,
    PUBSUB_CHANNELS,
    Channel,
    ChannelKind,
    channel_kind,
)
from .consumer import Consumer
from .dead_letter import DeadLetterHandler
from .local import LocalTransport
from .platform import PlatformTransport
from .publisher import Publisher


_transport: Optional[MessageTransport] = None


def create_transport(backend: Optional[str] = None) -> MessageTransport:
    """Factory: returns a new MessageTransport based on env or argument."""
    name = (backend or os.environ.get("TRANSPORT_BACKEND", "local")).strip().lower()
    if name == "local":
        return LocalTransport()
    if name == "redis":
        from .redis_transport import RedisTransport
        return RedisTransport()
    if name == "platform":
        return PlatformTransport()
    raise ValueError(f"Unknown TRANSPORT_BACKEND: {name!r}")


def init_transport(transport: MessageTransport) -> MessageTransport:
    """Install the process-wide MessageTransport singleton."""
    global _transport
    _transport = transport
    return transport


def get_transport() -> MessageTransport:
    """Return the installed singleton, creating one from env if missing."""
    global _transport
    if _transport is None:
        _transport = create_transport()
    return _transport


def reset_transport_for_tests() -> None:
    global _transport
    _transport = None


__all__ = [
    "MessageTransport",
    "ReceivedMessage",
    "HealthStatus",
    "Channel",
    "ChannelKind",
    "channel_kind",
    "ALL_CHANNELS",
    "ALL_STREAM_CHANNELS",
    "CROSS_DOMAIN_CHANNELS",
    "INTERNAL_STREAM_CHANNELS",
    "PUBSUB_CHANNELS",
    "INFRA_STREAM_CHANNELS",
    "Publisher",
    "Consumer",
    "DeadLetterHandler",
    "LocalTransport",
    "PlatformTransport",
    "create_transport",
    "init_transport",
    "get_transport",
    "reset_transport_for_tests",
]
