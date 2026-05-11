"""Phase 8: Approval gates — verdict-based posting gates."""

from dataclasses import dataclass
from typing import Optional

from ..guiders.base import Decision


@dataclass
class GateResult:
    """Result of checking an approval gate."""
    passed: bool
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
        }


class ApprovalGate:
    """Verdict-based gate for posting decisions."""

    @staticmethod
    def check_cascade_verdict(verdict: Optional[Decision]) -> GateResult:
        """Check if cascade verdict permits posting.

        BLOCK → posting halted
        ESCALATE → posting requires explicit dual approval override
        APPROVE → posting can proceed
        None → default allow (for backward compatibility)
        """
        if verdict is None:
            return GateResult(passed=True)

        if verdict == Decision.BLOCK:
            return GateResult(
                passed=False,
                reason="Cascade verdict is BLOCK — posting is not permitted",
            )

        if verdict == Decision.ESCALATE:
            return GateResult(
                passed=True,
                reason="Cascade verdict is ESCALATE — posting requires dual approval",
            )

        if verdict == Decision.APPROVE:
            return GateResult(
                passed=True,
                reason="Cascade verdict is APPROVE — posting can proceed",
            )

        return GateResult(passed=True)

    @staticmethod
    def check_approval_status(
        is_fully_approved: bool,
        cascade_verdict: Optional[Decision],
    ) -> GateResult:
        """Check if approval status permits posting.

        Requires:
        - Dual approval (BUDGET_OWNER + TREASURER)
        - No cascade BLOCK verdict
        """
        if cascade_verdict == Decision.BLOCK:
            return GateResult(
                passed=False,
                reason="Cascade verdict BLOCK prevents posting",
            )

        if not is_fully_approved:
            return GateResult(
                passed=False,
                reason="Dual approval required (BUDGET_OWNER + TREASURER)",
            )

        return GateResult(
            passed=True,
            reason="All approvals obtained and cascade verdict permits posting",
        )

    @staticmethod
    def can_post(
        is_fully_approved: bool,
        cascade_verdict: Optional[Decision],
    ) -> bool:
        """Simple boolean check: can this entry be posted?"""
        result = ApprovalGate.check_approval_status(is_fully_approved, cascade_verdict)
        return result.passed
