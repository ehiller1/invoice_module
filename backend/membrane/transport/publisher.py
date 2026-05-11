"""Publisher — thin wrapper over MessageTransport.publish.

Adds:
  - 2-attempt retry (the transport may also retry internally; this is the
    outer/business retry boundary).
  - Automatic dead-letter routing on terminal failure.
  - ImpactSignal pass-through (publish_signal serializes to dict).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import MessageTransport


class Publisher:
    def __init__(self, transport: MessageTransport) -> None:
        self.transport = transport

    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        last_err: Optional[Exception] = None
        for _ in range(2):
            try:
                return await self.transport.publish(channel, payload)
            except Exception as exc:
                last_err = exc
        # transport publish already DLQs internally, but we still escalate.
        await self.transport.dead_letter(channel, payload, f"publisher_failed: {last_err!r}")
        assert last_err is not None
        raise last_err

    async def publish_signal(self, signal: Any) -> str:
        """Publish an ImpactSignal-like object that has `.target_channel` and
        `.model_dump()` (pydantic v2) or `.dict()` (v1)."""
        payload = (
            signal.model_dump(mode="json") if hasattr(signal, "model_dump") else signal.dict()
        )
        channel = getattr(signal, "target_channel", None) or payload.get("target_channel")
        if not channel:
            raise ValueError("signal missing target_channel")
        return await self.publish(channel, payload)


__all__ = ["Publisher"]
