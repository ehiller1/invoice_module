"""Phase 8: Approval endpoints for dual sign-off."""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from ..auth import get_caller_role, has_role
from ..db import processing_job_store, journal_entry_store
from ..flow import _update_job
from ..membrane.approval.workflow import ApprovalRole, ApprovalDecision, ApprovalWorkflow
from ..membrane.approval.gates import ApprovalGate
from ..membrane.guiders.base import Decision
from ..models.schemas import JEStatus, ProcessingStatus

router = APIRouter(tags=["approvals"])

# Approval state tracking (job_id → ApprovalWorkflow)
_approval_workflows: Dict[str, ApprovalWorkflow] = {}


def _get_workflow(job_id: str) -> ApprovalWorkflow:
    """Get or create approval workflow for a job."""
    if job_id not in _approval_workflows:
        _approval_workflows[job_id] = ApprovalWorkflow()
    return _approval_workflows[job_id]


def _parse_cascade_verdict(verdict_str: Optional[str]) -> Optional[Decision]:
    """Parse cascade verdict string to Decision enum."""
    if not verdict_str:
        return None
    try:
        return Decision[verdict_str.upper()]
    except (KeyError, AttributeError):
        return None


@router.post("/api/jobs/{job_id}/approve/budget-owner")
async def approve_as_budget_owner(
    job_id: str,
    request: Request,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Budget Owner approves a job for treasurer review.

    RBAC: requires BUDGET_OWNER or TREASURER_ADMIN role.
    """
    actual = get_caller_role(request)
    if not has_role(actual, "BUDGET_OWNER") and not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks BUDGET_OWNER",
        )

    job = processing_job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    body = body or {}
    reasoning = body.get("reasoning", "")
    decision_str = body.get("decision", "APPROVE")

    if decision_str not in ["APPROVE", "REJECT"]:
        raise HTTPException(400, "Invalid decision; must be APPROVE or REJECT")

    decision = ApprovalDecision[decision_str]

    # Get or create workflow
    workflow = _get_workflow(job_id)

    # Set cascade verdict if provided
    if job.cascade_verdict:
        cascade_verdict = _parse_cascade_verdict(job.cascade_verdict)
        workflow.set_cascade_verdict(cascade_verdict)

    # Record approval
    workflow.record_approval(
        approver_role=ApprovalRole.BUDGET_OWNER,
        decision=decision,
        principal=actual or "unknown",
        reasoning=reasoning,
    )

    # Check if cascade blocks further approval
    can_proceed, halt_reason = workflow.check_cascade_gate()
    if not can_proceed:
        return {
            "status": "HALTED",
            "halt_reason": halt_reason,
            "job_id": job_id,
        }

    # Update job with budget owner decision
    job.budget_owner_decision = {
        "decision": decision.value,
        "principal": actual,
        "timestamp": datetime.utcnow().isoformat(),
        "reasoning": reasoning,
    }

    if decision == ApprovalDecision.REJECT:
        # Update status to rejected
        _update_job(job, ProcessingStatus.REJECTED)
        return {
            "status": "REJECTED",
            "reason": "Budget owner rejected approval",
            "job_id": job_id,
        }

    # Move to pending treasurer
    _update_job(job, ProcessingStatus.PENDING_TREASURER)

    result = workflow.get_result(job_id, job.journal_entry.entry_id if job.journal_entry else None)
    return {
        "status": "PENDING_TREASURER",
        "result": result.to_dict(),
        "job_id": job_id,
    }


@router.post("/api/jobs/{job_id}/approve/treasurer")
async def approve_as_treasurer(
    job_id: str,
    request: Request,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Treasurer approves a job for posting.

    RBAC: requires TREASURER_ADMIN role.
    After treasurer approval, the entry can be posted to ACS Realm.
    """
    from ..db.processing_jobs import processing_job_store

    actual = get_caller_role(request)
    if not has_role(actual, "TREASURER_ADMIN"):
        raise HTTPException(
            403,
            f"Forbidden: role '{actual or 'none'}' lacks TREASURER_ADMIN",
        )

    job = processing_job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    body = body or {}
    reasoning = body.get("reasoning", "")
    decision_str = body.get("decision", "APPROVE")

    if decision_str not in ["APPROVE", "REJECT"]:
        raise HTTPException(400, "Invalid decision; must be APPROVE or REJECT")

    decision = ApprovalDecision[decision_str]

    # Get or create workflow
    workflow = _get_workflow(job_id)

    # Set cascade verdict if provided
    if job.cascade_verdict:
        cascade_verdict = _parse_cascade_verdict(job.cascade_verdict)
        workflow.set_cascade_verdict(cascade_verdict)

    # Record approval
    workflow.record_approval(
        approver_role=ApprovalRole.TREASURER,
        decision=decision,
        principal=actual or "unknown",
        reasoning=reasoning,
    )

    # Check if cascade blocks further approval
    can_proceed, halt_reason = workflow.check_cascade_gate()
    if not can_proceed:
        return {
            "status": "HALTED",
            "halt_reason": halt_reason,
            "job_id": job_id,
        }

    # Update job with treasurer decision
    job.treasurer_decision = {
        "decision": decision.value,
        "principal": actual,
        "timestamp": datetime.utcnow().isoformat(),
        "reasoning": reasoning,
    }

    if decision == ApprovalDecision.REJECT:
        # Update status to rejected
        _update_job(job, ProcessingStatus.REJECTED)
        return {
            "status": "REJECTED",
            "reason": "Treasurer rejected approval",
            "job_id": job_id,
        }

    # Check if fully approved
    if not workflow.is_fully_approved():
        return {
            "status": "PENDING_DUAL_APPROVAL",
            "missing_approvals": ["BUDGET_OWNER"] if not workflow.records else [],
            "job_id": job_id,
        }

    # Fully approved — move to TREASURER_APPROVED status
    from ..flow import _update_job
    from ..models.schemas import ProcessingStatus

    _update_job(job, ProcessingStatus.TREASURER_APPROVED)

    result = workflow.get_result(job_id, job.journal_entry.entry_id if job.journal_entry else None)
    return {
        "status": "APPROVED",
        "can_post": result.can_post,
        "result": result.to_dict(),
        "job_id": job_id,
    }


@router.get("/api/jobs/{job_id}/approval-status")
async def get_approval_status(
    job_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Get current approval status for a job."""
    from ..db.processing_jobs import processing_job_store

    job = processing_job_store.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    workflow = _get_workflow(job_id)

    if job.cascade_verdict:
        cascade_verdict = _parse_cascade_verdict(job.cascade_verdict)
        workflow.set_cascade_verdict(cascade_verdict)

    result = workflow.get_result(job_id, job.journal_entry.entry_id if job.journal_entry else None)

    # Check if posting is allowed
    can_post_gate = ApprovalGate.check_approval_status(
        workflow.is_fully_approved(),
        workflow.cascade_verdict,
    )

    return {
        "job_id": job_id,
        "status": job.status.value,
        "cascade_verdict": job.cascade_verdict,
        "approval_records": [r.to_dict() for r in workflow.records],
        "is_fully_approved": workflow.is_fully_approved(),
        "is_rejected": workflow.is_rejected(),
        "can_post": can_post_gate.passed,
        "gate_result": can_post_gate.to_dict(),
        "result": result.to_dict(),
    }


