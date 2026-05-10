"""Event schemas (Pydantic) for the event-driven foundation.

The event log is append-only and immutable. Every domain change emits one
or more events; existing GL tables are derived projections.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Canonical event types. Add new types here; never repurpose old ones."""

    DOCUMENT_RECEIVED         = "DocumentReceived"
    CONTEXT_ASSEMBLED         = "ContextAssembled"
    CLASSIFICATION_PROPOSED   = "ClassificationProposed"
    DECISION_RECORDED         = "DecisionRecorded"
    APPROVAL_GRANTED          = "ApprovalGranted"
    APPROVAL_DENIED           = "ApprovalDenied"
    TRANSACTION_POSTED        = "TransactionPosted"
    RESTRICTION_APPLIED       = "RestrictionApplied"
    RESTRICTION_RELEASED      = "RestrictionReleased"
    RESTRICTION_REJECTED      = "RestrictionRejected"
    PAYMENT_INITIATED         = "PaymentInitiated"
    PAYMENT_CLEARED           = "PaymentCleared"
    PAYMENT_FAILED            = "PaymentFailed"
    POSTING_BLOCKED           = "PostingBlocked"
    BUDGET_THRESHOLD_CROSSED  = "BudgetThresholdCrossed"
    BANK_ITEM_OBSERVED        = "BankItemObserved"
    STRUCTURAL_MATCH          = "StructuralMatchObserved"
    YTD_ADJUSTED              = "YTDAdjusted"
    DISAVOWED                 = "Disavowed"


class TagKind(str, Enum):
    """Tag dimensions an event can carry. Multi-valued per event."""

    ACCOUNT      = "account"       # CoA tag value (e.g., "1010")
    FUND         = "fund"          # fund tag value (e.g., "GEN")
    RESTRICTION  = "restriction"   # restriction class
    MISSION      = "mission"       # mission category (worship/outreach/etc.)
    VENDOR       = "vendor"        # vendor identifier
    PERIOD       = "period"        # YYYY-MM
    DENOMINATION = "denomination"  # denomination type
    DOCUMENT     = "document"      # source document reference
    JOB          = "job"           # processing job id
    ENTRY        = "entry"         # journal entry id
    PAYMENT      = "payment"       # payment id
    MINISTRY     = "ministry"      # ministry/program (e.g., "worship", "youth", "community_outreach")
    BENEFICIARY  = "beneficiary"   # primary beneficiary (e.g., "congregation", "community", "staff")
    COST_CENTER  = "cost_center"   # operational cost center/department
    GEOGRAPHY    = "geography"     # location/campus/site
    MISSION_IMPACT = "mission_impact"  # mission outcome (e.g., "spiritual_growth", "community_service")
    FUNDING_SOURCE = "funding_source"  # source of funds (e.g., "donations", "grants", "earned_income", "endowment")
    CAPITALIZATION_ELIGIBLE = "capitalization_eligible"  # asset class flag (true/false)
    GIFT_PURPOSE = "gift_purpose"  # donor intent/designation (e.g., "undesignated", "designated", "endowment")


class EventTag(BaseModel):
    """A single tag on an event."""

    tag_kind: TagKind
    tag_value: str = Field(..., max_length=255)


class FinancialEvent(BaseModel):
    """The base envelope for every event written to the log.

    The `payload` carries event-type-specific data; `tags` is the queryable
    dimension. The CoA is realized as ACCOUNT tags applied to events — never
    as a destination row on the event itself.
    """

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    church_id: str  # external church_id; emitter resolves to PK
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    actor: Optional[str] = None
    confidence: Optional[Decimal] = None  # 0.0–1.0
    payload: Dict[str, Any] = Field(default_factory=dict)
    caused_by: List[UUID] = Field(default_factory=list)
    correlation_id: Optional[str] = None
    tags: List[EventTag] = Field(default_factory=list)

    def add_tag(self, kind: TagKind, value: str) -> "FinancialEvent":
        """Fluent helper to attach a tag."""
        self.tags.append(EventTag(tag_kind=kind, tag_value=str(value)))
        return self
