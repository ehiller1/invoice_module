"""Dead-letter handler — small convenience layer over transport.dead_letter."""
from __future__ import annotations

from typing import Any, Dict

from .base import MessageTransport


class DeadLetterHandler:
    def __init__(self, transport: MessageTransport) -> None:
        self.transport = transport

    async def record(self, channel: str, payload: Dict[str, Any], reason: str) -> str:
        return await self.transport.dead_letter(channel, payload, reason)


__all__ = ["DeadLetterHandler"]
