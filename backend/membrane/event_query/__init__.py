"""Event query singleton and factory (Phase 2)."""
from __future__ import annotations

import os
from typing import Optional

from .base import EventQueryTransport, EventRecord, QueryFilter, QueryHealth
from .local import LocalEventQuery
from .platform import EmbarkEventQuery

_query: Optional[EventQueryTransport] = None


def create_query_transport(backend: Optional[str] = None) -> EventQueryTransport:
    name = (backend or os.environ.get("EVENT_QUERY_BACKEND", "local")).strip().lower()
    if name == "local":
        return LocalEventQuery()
    if name == "redis":
        from .redis_query import RedisEventQuery
        return RedisEventQuery()
    if name == "platform":
        return EmbarkEventQuery()
    raise ValueError(f"Unknown EVENT_QUERY_BACKEND: {name!r}")


def init_query_transport(q: EventQueryTransport) -> EventQueryTransport:
    global _query
    _query = q
    return q


def get_query_transport() -> EventQueryTransport:
    global _query
    if _query is None:
        _query = create_query_transport()
    return _query


def reset_query_transport_for_tests() -> None:
    global _query
    _query = None


__all__ = [
    "EventQueryTransport",
    "EventRecord",
    "QueryFilter",
    "QueryHealth",
    "LocalEventQuery",
    "EmbarkEventQuery",
    "create_query_transport",
    "init_query_transport",
    "get_query_transport",
    "reset_query_transport_for_tests",
]
