"""Event-driven foundation (Phase 5a).

Events are the system of record. The Phase 4 GL tables become projections.
"""
from .schemas import (
    EventType,
    TagKind,
    FinancialEvent,
    EventTag,
)
from .emitter import emit_event, emit_event_in_txn

__all__ = [
    "EventType",
    "TagKind",
    "FinancialEvent",
    "EventTag",
    "emit_event",
    "emit_event_in_txn",
]
