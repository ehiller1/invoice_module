"""Phase 8: Approval + ACS Posting

This module implements verdict-gated approval and posting workflows.
"""

from .workflow import ApprovalWorkflow, ApprovalDecision, ApprovalResult
from .gates import ApprovalGate, GateResult

__all__ = [
    "ApprovalWorkflow",
    "ApprovalDecision",
    "ApprovalResult",
    "ApprovalGate",
    "GateResult",
]
