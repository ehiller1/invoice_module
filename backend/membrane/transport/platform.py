"""PlatformTransport — stub for the future Embark platform mesh.

This implementation is intentionally inert: it documents the integration
points (CHANNEL_MAP, PLATFORM_MESH_URL env var) so that the swap to a
hosted message bus is a single class change. All methods raise
NotImplementedError today, except `health` which reports the missing
backend so /health/redis surfaces the stub clearly.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import HealthStatus, MessageTransport, ReceivedMessage
from .channels import Channel


# Map internal channel constants to platform-specific topic names.
# The platform team will populate these once the mesh schema is finalized.
CHANNEL_MAP: Dict[str, str] = {
    Channel.IMPACT_PROPOSED_INVOICE_INGESTED: "embark.impact.proposed.invoice_ingested",
    Channel.STEWARDSHIP_PROPOSED_BUDGET_CHANGED: "embark.stewardship.proposed.budget_changed",
    Channel.PASTORAL_PROPOSED_RESTRICTION_FLAGGED: "embark.pastoral.proposed.restriction_flagged",
    Channel.IMPACT_PROPOSED_JE_DRAFTED: "embark.impact.proposed.je_drafted",
    Channel.IMPACT_PROPOSED_PAYMENT_QUEUED: "embark.impact.proposed.payment_queued",
    Channel.IMPACT_RESOLVED_JE_POSTED: "embark.impact.resolved.je_posted",
    Channel.IMPACT_RESOLVED_PAYMENT_SENT: "embark.impact.resolved.payment_sent",
    Channel.IMPACT_RESOLVED_RECON_MATCHED: "embark.impact.resolved.recon_matched",
    Channel.IMPACT_ADVISORY_BUDGET_THRESHOLD: "embark.impact.advisory.budget_threshold",
    Channel.IMPACT_ADVISORY_RESTRICTION_REJECTED: "embark.impact.advisory.restriction_rejected",
    Channel.PROCESSING_STATUS: "embark.advisory.processing_status",
    Channel.INFRA_DEAD_LETTER: "embark.infra.dead_letter",
    Channel.INFRA_AUDIT: "embark.infra.audit",
}


class PlatformTransport(MessageTransport):
    """Stub: requires a live Embark mesh endpoint to operate."""

    backend_name = "platform"

    def __init__(self) -> None:
        self.mesh_url = os.environ.get("PLATFORM_MESH_URL", "")

    def _not_implemented(self, op: str) -> NotImplementedError:
        return NotImplementedError(
            f"PlatformTransport.{op} is a stub; set PLATFORM_MESH_URL and "
            f"implement Embark mesh adapter to use TRANSPORT_BACKEND=platform"
        )

    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        raise self._not_implemented("publish")

    async def broadcast(self, channel: str, payload: Dict[str, Any]) -> None:
        raise self._not_implemented("broadcast")

    async def consume_batch(
        self, channel: str, group: str, consumer: str, *, count: int = 16, block_ms: int = 1000
    ) -> List[ReceivedMessage]:
        raise self._not_implemented("consume_batch")

    async def ack(self, channel: str, group: str, delivery_id: str) -> None:
        raise self._not_implemented("ack")

    async def nack(self, channel: str, group: str, delivery_id: str) -> None:
        raise self._not_implemented("nack")

    async def ensure_group(self, channel: str, group: str) -> None:
        raise self._not_implemented("ensure_group")

    async def dead_letter(self, original_channel: str, payload: Dict[str, Any], reason: str) -> str:
        raise self._not_implemented("dead_letter")

    async def health(self) -> HealthStatus:
        return HealthStatus(
            healthy=False,
            backend=self.backend_name,
            detail=(
                "stub: PLATFORM_MESH_URL=" + (self.mesh_url or "<unset>") +
                "; Embark mesh adapter not implemented"
            ),
        )


__all__ = ["PlatformTransport", "CHANNEL_MAP"]
