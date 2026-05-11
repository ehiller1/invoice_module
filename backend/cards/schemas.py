"""Phase 10: Unified Card Schemas (Memory, Plan, Decision Packets).

Memory Cards: Contextual memory written by agents/cabinet members
Plan Cards: Projected GL state or forecast snapshots
Decision Packets: Immutable decision records with ledger chain reference
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class CardType(str, Enum):
    """All card types in unified store."""
    MEMORY = "memory"
    PLAN = "plan"
    DECISION = "decision"


class Card(BaseModel):
    """Base card structure."""
    card_id: str
    card_type: CardType
    principal: str  # who created this card (actor_id or agent name)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCard(Card):
    """Contextual memory written by agents/cabinet members (Phase 10).

    Used by: cabinet runners, MVP agents to store decision context,
    digests, screening notes, projections.
    """
    card_type: CardType = CardType.MEMORY
    content: str  # Serialized memory payload (JSON string)
    confidence: float = 0.5  # 0.0-1.0, how confident in this memory
    references: list[str] = Field(default_factory=list)  # card_ids this references
    tags: list[str] = Field(default_factory=list)  # categorization tags

    class Config:
        use_enum_values = False


class PlanCard(Card):
    """Projected GL state or forecast snapshot (Phase 10).

    Stores GL account balances at a point in time, assumptions used to project,
    and metadata about the projection period.
    """
    card_type: CardType = CardType.PLAN
    period: str  # "2026-05-11" (date) or "2026-05-Q2" (period)
    accounts: dict[str, Decimal]  # { "10000": Decimal("1000.00"), ... }
    assumptions: dict[str, Any] = Field(default_factory=dict)  # what was assumed
    scenario: str = "baseline"  # baseline, optimistic, pessimistic, etc.

    class Config:
        use_enum_values = False


class DecisionPacket(Card):
    """Immutable decision record with ledger chain reference (Phase 10).

    Links to Decision Ledger entry. Captured when a decision is made.
    Includes voting approvers, confidence, alternatives considered.
    """
    card_type: CardType = CardType.DECISION
    decision_id: str  # links to decision_ledger entry
    category: str  # RECOGNIZE, CODE, ROUTE, APPROVE, OVERRIDE, DISAVOW
    verdict: str  # Decision.APPROVE / ESCALATE / BLOCK
    reasoning: str
    evidence_refs: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.5
    approvers: list[str] = Field(default_factory=list)  # who approved (actor_ids)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Phase 10.5-10.6: Governance categorization tags
    categorization_tags: list[dict[str, Any]] = Field(default_factory=list)
    # [{ "tag": "approve", "timestamp": "2026-05-11T...", "confidence": 0.95 }, ...]

    class Config:
        use_enum_values = False
