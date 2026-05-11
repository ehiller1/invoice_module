"""Channel constants for the Embark Membrane (Phase 2).

13 channels total:
  - 3 cross-domain Streams (impact / stewardship / pastoral proposals)
  - 7 internal Streams (impact:proposed / impact:resolved / impact:advisory ...)
  - 1 advisory Pub/Sub (processing_status)
  - 2 infrastructure Streams (dead_letter, audit)

Channel names match the ImpactSignal `target_channel` regex
`^impact:[a-z_]+:[a-z0-9_]+$` for cross-domain/internal Streams. Infra and
advisory channels live outside the impact namespace and are validated
separately.
"""
from __future__ import annotations

from enum import Enum
from typing import FrozenSet


class ChannelKind(str, Enum):
    STREAM = "stream"  # Redis Streams (XADD/XREADGROUP, durable)
    PUBSUB = "pubsub"  # Redis Pub/Sub (ephemeral broadcast)


class Channel:
    """All 13 membrane channels as string constants.

    Use these symbols in publisher/consumer wiring; do not hard-code strings.
    """

    # ---- Cross-domain proposals (3) ----
    IMPACT_PROPOSED_INVOICE_INGESTED = "impact:proposed:invoice_ingested"
    STEWARDSHIP_PROPOSED_BUDGET_CHANGED = "stewardship:proposed:budget_changed"
    PASTORAL_PROPOSED_RESTRICTION_FLAGGED = "pastoral:proposed:restriction_flagged"

    # ---- Internal impact streams (7) ----
    IMPACT_PROPOSED_JE_DRAFTED = "impact:proposed:je_drafted"
    IMPACT_PROPOSED_PAYMENT_QUEUED = "impact:proposed:payment_queued"
    IMPACT_RESOLVED_JE_POSTED = "impact:resolved:je_posted"
    IMPACT_RESOLVED_PAYMENT_SENT = "impact:resolved:payment_sent"
    IMPACT_RESOLVED_RECON_MATCHED = "impact:resolved:recon_matched"
    IMPACT_ADVISORY_BUDGET_THRESHOLD = "impact:advisory:budget_threshold"
    IMPACT_ADVISORY_RESTRICTION_REJECTED = "impact:advisory:restriction_rejected"

    # ---- Advisory Pub/Sub (1) ----
    PROCESSING_STATUS = "advisory:processing_status"

    # ---- Infrastructure Streams (2) ----
    INFRA_DEAD_LETTER = "infra:dead_letter"
    INFRA_AUDIT = "infra:audit"


CROSS_DOMAIN_CHANNELS: FrozenSet[str] = frozenset({
    Channel.IMPACT_PROPOSED_INVOICE_INGESTED,
    Channel.STEWARDSHIP_PROPOSED_BUDGET_CHANGED,
    Channel.PASTORAL_PROPOSED_RESTRICTION_FLAGGED,
})

INTERNAL_STREAM_CHANNELS: FrozenSet[str] = frozenset({
    Channel.IMPACT_PROPOSED_JE_DRAFTED,
    Channel.IMPACT_PROPOSED_PAYMENT_QUEUED,
    Channel.IMPACT_RESOLVED_JE_POSTED,
    Channel.IMPACT_RESOLVED_PAYMENT_SENT,
    Channel.IMPACT_RESOLVED_RECON_MATCHED,
    Channel.IMPACT_ADVISORY_BUDGET_THRESHOLD,
    Channel.IMPACT_ADVISORY_RESTRICTION_REJECTED,
})

PUBSUB_CHANNELS: FrozenSet[str] = frozenset({
    Channel.PROCESSING_STATUS,
})

INFRA_STREAM_CHANNELS: FrozenSet[str] = frozenset({
    Channel.INFRA_DEAD_LETTER,
    Channel.INFRA_AUDIT,
})

ALL_STREAM_CHANNELS: FrozenSet[str] = (
    CROSS_DOMAIN_CHANNELS | INTERNAL_STREAM_CHANNELS | INFRA_STREAM_CHANNELS
)

ALL_CHANNELS: FrozenSet[str] = ALL_STREAM_CHANNELS | PUBSUB_CHANNELS


def channel_kind(channel: str) -> ChannelKind:
    """Return the transport kind for a channel (stream vs pub/sub)."""
    if channel in PUBSUB_CHANNELS:
        return ChannelKind.PUBSUB
    if channel in ALL_STREAM_CHANNELS:
        return ChannelKind.STREAM
    raise ValueError(f"Unknown channel: {channel!r}")


assert len(ALL_CHANNELS) == 13, f"expected 13 channels, found {len(ALL_CHANNELS)}"


__all__ = [
    "Channel",
    "ChannelKind",
    "CROSS_DOMAIN_CHANNELS",
    "INTERNAL_STREAM_CHANNELS",
    "PUBSUB_CHANNELS",
    "INFRA_STREAM_CHANNELS",
    "ALL_STREAM_CHANNELS",
    "ALL_CHANNELS",
    "channel_kind",
]
