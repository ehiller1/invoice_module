"""Card types and lifecycle management (FRD §9.1).

Eight persisted card types:
- EventCard: Economic Event with provenance
- DecisionCard: Decision with reasoning chain
- ExceptionCard: Exception requiring human judgment
- PolicyCard: Policy decision with effective date
- ForecastCard: Financial projection
- ReconciliationCard: Matched/unmatched transaction
- RecommendationCard: NBA candidate with projected impact
- QuestionCard: User query with answer history

All cards carry privacy_class (P0-P3) and version (optimistic locking).
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel


class PrivacyClass(str, Enum):
    """Privacy classification for card fields (FRD UCS-10)."""
    P0 = "P0"  # Pastoral content, visible only at T3+
    P1 = "P1"  # Donor PII, masked below T2, reveal with logging
    P2 = "P2"  # Internal staff, visible at T1+
    P3 = "P3"  # Public, visible to all


class CardState(str, Enum):
    """Card lifecycle states."""
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    PAUSED = "PAUSED"


class EventCard(BaseModel):
    """Economic Event card (FRD §3.2 + §9.1)."""
    event_id: str
    event_type: str  # namespaced: "recognition.asc606", "reconcile.missing_event", etc.
    emission_ts: datetime
    effective_ts: datetime
    provenance: Dict[str, Any]  # source_system, source_id, raw_payload_ref, etc.
    counterparty: Dict[str, str]  # id, type, display_name
    amount: float
    currency: str = "USD"
    classification: Dict[str, Any]  # gl_account, fund, restriction_class, etc.
    confidence: float = 1.0
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class DecisionCard(BaseModel):
    """Decision card with reasoning chain (FRD §14.1)."""
    decision_id: str
    decision_type: str  # "recognize", "code", "override", etc.
    authoring_actor: Dict[str, Any]  # actor_type, actor_id, authority_tier, cabinet_principal_id
    evidence_refs: List[str] = []
    reasoning: Dict[str, Any]  # policy_invoked, inputs, inference_chain, conclusion
    alternatives: List[Dict[str, Any]] = []  # each with rejection rationale
    confidence: float = 1.0
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    linked_event_ids: List[str] = []
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class ExceptionCard(BaseModel):
    """Exception card requiring human adjudication."""
    exception_id: str
    exception_type: str  # "ambiguous_gift", "capitalization_gap", "pastoral_conflict", etc.
    state: CardState = CardState.OPEN
    summary: str
    details: Dict[str, Any]
    assigned_to: Optional[str] = None  # actor_id
    priority: str = "NORMAL"  # HIGH, NORMAL, LOW
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class PolicyCard(BaseModel):
    """Policy decision card (discretionary or governance)."""
    policy_id: str
    policy_type: str  # "discretionary_fund_size", "new_channel", "quasi_endowment_draw", etc.
    state: CardState = CardState.OPEN
    title: str
    description: str
    proposed_action: str
    effective_date: Optional[datetime] = None
    voted_by: List[Dict[str, Any]] = []  # {actor_id, tier, vote: "yes"/"no"/"abstain"}
    decision: Optional[str] = None  # "approved", "rejected", "tabled"
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class RecommendationCard(BaseModel):
    """NBA Recommendation card with projected impact (FRD §11.1)."""
    recommendation_id: str
    state: CardState = CardState.OPEN
    title: str
    description: str
    candidates: List[Dict[str, Any]]  # each with id, description, impact_projection
    selected_candidate: Optional[str] = None
    rationale: str
    impact_projection: Dict[str, Any]  # cash_impact, covenant_impact, mission_impact, peer_impact
    decision_deadline: Optional[datetime] = None
    decided_by: Optional[str] = None  # actor_id
    decision: Optional[str] = None  # "accepted", "declined", "modified"
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class ReconciliationCard(BaseModel):
    """Reconciliation card for matched/unmatched transactions."""
    reconciliation_id: str
    state: CardState = CardState.OPEN
    transaction_date: datetime
    description: str
    amount: float
    account_id: str
    matching_status: str  # "matched", "partial", "unmatched", "missing_event"
    matched_je_id: Optional[str] = None
    exceptions: List[str] = []
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()


class QuestionCard(BaseModel):
    """Question/Query card from Question Canvas."""
    question_id: str
    state: CardState = CardState.OPEN
    query: str  # NL user query
    intent: Optional[str] = None  # classified intent from router
    answer: Optional[str] = None  # rendered answer/projection
    provenance: List[Dict[str, Any]] = []  # trace to source events
    follow_on_suggestions: List[str] = []  # recommended intents
    asker_id: Optional[str] = None  # actor_id
    privacy_class: PrivacyClass = PrivacyClass.P3
    version: int = 1
    created_at: datetime = None
    updated_at: datetime = None

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = datetime.utcnow()
        if not self.updated_at:
            self.updated_at = datetime.utcnow()
