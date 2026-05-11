"""Phase 8: Approval workflow — verdict-gated dual approval."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..guiders.base import Decision, Verdict


class ApprovalRole(str, Enum):
    """Roles that can approve journal entries."""
    TREASURER = "TREASURER"
    BUDGET_OWNER = "BUDGET_OWNER"
    FINANCE_STAFF = "FINANCE_STAFF"


class ApprovalDecision(str, Enum):
    """Decision made during approval."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"  # Send to higher authority


@dataclass(frozen=True)
class ApprovalRecord:
    """Record of a single approval decision."""
    approver_role: ApprovalRole
    decision: ApprovalDecision
    timestamp: datetime
    principal: str  # Approver's identifier
    reasoning: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "approver_role": self.approver_role.value,
            "decision": self.decision.value,
            "timestamp": self.timestamp.isoformat(),
            "principal": self.principal,
            "reasoning": self.reasoning,
        }


@dataclass
class ApprovalResult:
    """Result of approval workflow execution."""
    job_id: str
    je_id: Optional[str]
    cascade_verdict: Optional[Decision]
    approval_records: list[ApprovalRecord] = field(default_factory=list)
    is_approved: bool = False
    is_blocked: bool = False
    can_post: bool = False
    halt_reason: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "je_id": self.je_id,
            "cascade_verdict": self.cascade_verdict.value if self.cascade_verdict else None,
            "approval_records": [r.to_dict() for r in self.approval_records],
            "is_approved": self.is_approved,
            "is_blocked": self.is_blocked,
            "can_post": self.can_post,
            "halt_reason": self.halt_reason,
            "error": self.error,
        }


class ApprovalWorkflow:
    """Approval workflow gated by guider cascade verdicts."""

    def __init__(self):
        self.records: list[ApprovalRecord] = []
        self.cascade_verdict: Optional[Decision] = None

    def set_cascade_verdict(self, verdict: Optional[Decision]) -> None:
        """Set the cascade verdict from Phase 7 orchestrator."""
        self.cascade_verdict = verdict

    def check_cascade_gate(self) -> tuple[bool, Optional[str]]:
        """Check if cascade verdict allows approval.

        Returns:
            (can_proceed, halt_reason): If halt_reason is set, approval is blocked.
        """
        if self.cascade_verdict is None:
            return True, None

        if self.cascade_verdict == Decision.BLOCK:
            return False, "Cascade verdict is BLOCK — posting halted"

        if self.cascade_verdict == Decision.ESCALATE:
            # ESCALATE allows proceeding but may require dual approval
            return True, None

        if self.cascade_verdict == Decision.APPROVE:
            return True, None

        return True, None

    def record_approval(
        self,
        approver_role: ApprovalRole,
        decision: ApprovalDecision,
        principal: str,
        reasoning: Optional[str] = None,
    ) -> None:
        """Record an approval decision."""
        record = ApprovalRecord(
            approver_role=approver_role,
            decision=decision,
            timestamp=datetime.utcnow(),
            principal=principal,
            reasoning=reasoning,
        )
        self.records.append(record)

    def is_fully_approved(self) -> bool:
        """Check if all required approvals are in place."""
        # Dual approval required: BUDGET_OWNER + TREASURER
        budget_owner_approved = any(
            r.approver_role == ApprovalRole.BUDGET_OWNER
            and r.decision == ApprovalDecision.APPROVE
            for r in self.records
        )
        treasurer_approved = any(
            r.approver_role == ApprovalRole.TREASURER
            and r.decision == ApprovalDecision.APPROVE
            for r in self.records
        )

        return budget_owner_approved and treasurer_approved

    def is_rejected(self) -> bool:
        """Check if any approver rejected the entry."""
        return any(r.decision == ApprovalDecision.REJECT for r in self.records)

    def requires_dual_approval(self) -> bool:
        """Determine if dual approval is required based on cascade verdict."""
        if self.cascade_verdict == Decision.ESCALATE:
            return True
        # Could add other logic here based on amount, risk, etc.
        return True  # Phase 8: always require dual approval

    def get_result(self, job_id: str, je_id: Optional[str] = None) -> ApprovalResult:
        """Get the current approval result."""
        can_proceed, halt_reason = self.check_cascade_gate()

        if not can_proceed:
            return ApprovalResult(
                job_id=job_id,
                je_id=je_id,
                cascade_verdict=self.cascade_verdict,
                approval_records=self.records,
                is_blocked=True,
                halt_reason=halt_reason,
            )

        if self.is_rejected():
            return ApprovalResult(
                job_id=job_id,
                je_id=je_id,
                cascade_verdict=self.cascade_verdict,
                approval_records=self.records,
                halt_reason="Entry rejected by approver",
            )

        is_approved = self.is_fully_approved()
        can_post = is_approved and can_proceed

        return ApprovalResult(
            job_id=job_id,
            je_id=je_id,
            cascade_verdict=self.cascade_verdict,
            approval_records=self.records,
            is_approved=is_approved,
            is_blocked=not can_proceed,
            can_post=can_post,
            halt_reason=halt_reason if not can_proceed else None,
        )
