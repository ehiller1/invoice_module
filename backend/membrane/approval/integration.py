"""Phase 8: Integration of cascade verdicts into approval + posting workflow."""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from ..guiders.base import Decision
from ..guiders.cascade import GuiderCascade
from ..envelope import ImpactSignal


def evaluate_cascade_verdict_for_job(
    job: Any,
    cascade: GuiderCascade,
) -> Optional[Decision]:
    """Evaluate cascade verdict for a job based on key signals.

    This is a Phase 8 helper that evaluates what the cascade verdict would be
    for the job's signals (invoice ingested, journal entry ready, etc).

    In Phase 7+, the orchestrator runs as a consumer and evaluates signals in real-time.
    In Phase 8, we can call this helper to get verdicts for approval gating.
    """
    # For Phase 8, we evaluate based on job properties that would trigger
    # cascade decisions
    try:
        # Check if job has fund restriction violation (hard block)
        if job.escalation_reason and "restriction" in job.escalation_reason.lower():
            return Decision.BLOCK

        # Check reviewed allocations for escalations (would trigger cascade check)
        if job.reviewed_allocations:
            for line in job.reviewed_allocations.lines:
                if hasattr(line, "verdict"):
                    from ...models import Verdict
                    if line.verdict == Verdict.ESCALATE:
                        # Build a synthetic signal to run through cascade
                        signal_name = "MAPPING_CONFIDENCE_LOW"
                        if "restriction" in str(line.reasons):
                            signal_name = "FUND_RESTRICTION_VIOLATION"
                        elif "policy" in str(line.reasons):
                            signal_name = "POLICY_VIOLATION"

                        # Create minimal signal for cascade evaluation
                        signal = _create_minimal_signal(signal_name, job)
                        try:
                            result = cascade.evaluate(signal)
                            if result.final_decision == Decision.BLOCK:
                                return Decision.BLOCK
                            if result.final_decision == Decision.ESCALATE:
                                return Decision.ESCALATE
                        except Exception:
                            pass

        # Default: no hard blocks, check if escalation is needed
        if job.escalation_level == "TREASURER":
            return Decision.ESCALATE

        # No issues found
        return Decision.APPROVE

    except Exception:
        # If evaluation fails, default to allowing approval but requiring escalation
        return Decision.ESCALATE


def _create_minimal_signal(signal_name: str, job: Any) -> ImpactSignal:
    """Create a minimal ImpactSignal for cascade evaluation."""
    from ..perturbations import perturbation_registry
    from ..transport.channels import Channel

    # Get perturbation metadata
    try:
        perturbation = perturbation_registry.get(signal_name)
    except Exception:
        perturbation = None

    # Map signal name to channel
    channel_map = {
        "INVOICE_INGESTED": Channel.INVOICE_INGESTED,
        "MAPPING_CONFIDENCE_LOW": Channel.MAPPING_CONFIDENCE_LOW,
        "BUDGET_OVERAGE_RISK": Channel.BUDGET_OVERAGE_RISK,
        "FUND_RESTRICTION_VIOLATION": Channel.FUND_RESTRICTION_VIOLATION,
        "POLICY_VIOLATION": Channel.POLICY_VIOLATION,
        "JOURNAL_ENTRY_READY": Channel.JOURNAL_ENTRY_READY,
    }

    signal = ImpactSignal(
        signal_id=perturbation.id if perturbation else 59,
        signal_name=signal_name,
        event_id=f"eval-{job.job_id}-{uuid4().hex[:8]}",
        occurred_at=job.updated_at or datetime.utcnow(),
        privacy_class=perturbation.privacy_class if perturbation else "P1",
        crosses_membrane=perturbation.crosses_membrane if perturbation else True,
        target_channel=channel_map.get(signal_name, Channel.INVOICE_INGESTED),
        payload={
            "job_id": job.job_id,
            "church_id": job.church_id,
            "document_type": job.document_type.value if hasattr(job, "document_type") and job.document_type else "INVOICE",
        },
        source="phase8-approval-integration",
    )
    return signal
