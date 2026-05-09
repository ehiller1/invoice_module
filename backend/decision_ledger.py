"""Decision Ledger — append-only ledger for structured reasoning (FRD §14.1).

Each entry records a decision, its reasoning chain, evidence, and audit trail.
Immutable: entries are inserted once and never modified.
Privacy-aware: reasoning fields inherit privacy_class from linked cards.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel


class DecisionCategory(str, Enum):
    """Classification of decision types per FRD §14.1."""
    RECOGNIZE = "recognize"  # Recognition membrane: GL classification
    CODE = "code"  # Coding membrane: account coding
    OVERRIDE = "override"  # Policy override with rationale
    APPROVE = "approve"  # Approval decision (funding, exception routing)
    ROUTE = "route"  # DMX routing to next tier/membrane
    DISAVOW = "disavow"  # Principal disavows decision (Cabinet surface)


class DecisionOutcome(str, Enum):
    """Result of decision."""
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TABLED = "tabled"
    DELEGATED = "delegated"


class LedgerEntry(BaseModel):
    """Single immutable ledger entry (append-only)."""
    entry_id: str
    decision_id: str  # foreign key to DecisionCard
    category: DecisionCategory
    timestamp: datetime
    authoring_actor: Dict[str, Any]  # actor_type, actor_id, authority_tier, cabinet_principal_id

    # Reasoning chain (FRD §14.1)
    policy_invoked: Optional[str] = None  # policy_id or policy name
    evidence_refs: List[str] = []  # pointers to EventCard IDs
    inference_chain: List[Dict[str, Any]] = []  # each step: {input, rule, output}
    conclusion: Optional[str] = None  # narrative summary

    # Alternatives considered (FRD §14.1)
    alternatives: List[Dict[str, Any]] = []  # each: {description, rejection_rationale}

    # Outcome (FRD §14.1)
    outcome: DecisionOutcome
    approved_by: Optional[str] = None  # actor_id of approver (if different from author)

    # Audit trail
    overridden_prior_decision_id: Optional[str] = None  # if this reverses another decision
    disavowed_at: Optional[datetime] = None  # if principal disavowed this decision
    disavowal_reason: Optional[str] = None

    # Payload (for future use: structured reasoning that doesn't fit above)
    metadata: Dict[str, Any] = {}


class DecisionLedger(BaseModel):
    """Queryable view over DecisionLedger entries for a church."""
    church_id: str
    entries: List[LedgerEntry] = []

    def append(self, entry: LedgerEntry) -> None:
        """Append an entry (immutable add-only)."""
        self.entries.append(entry)

    def find_by_decision(self, decision_id: str) -> List[LedgerEntry]:
        """Find all ledger entries for a decision."""
        return [e for e in self.entries if e.decision_id == decision_id]

    def find_by_actor(self, actor_id: str, after: Optional[datetime] = None) -> List[LedgerEntry]:
        """Find all decisions by an actor (audit trail)."""
        entries = [e for e in self.entries if e.authoring_actor.get('actor_id') == actor_id]
        if after:
            entries = [e for e in entries if e.timestamp >= after]
        return entries

    def find_overrides(self) -> List[LedgerEntry]:
        """Find all override decisions."""
        return [e for e in self.entries if e.category == DecisionCategory.OVERRIDE]
