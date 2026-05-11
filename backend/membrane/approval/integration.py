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
                            result = cascade.evaluate(signal.model_dump())
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
    from ..perturbations import get_perturbation
    from ..transport.channels import Channel

    # Map signal name to the correct Channel constant
    channel_map = {
        "INVOICE_INGESTED": Channel.IMPACT_PROPOSED_INVOICE_INGESTED,
        "MAPPING_CONFIDENCE_LOW": Channel.IMPACT_PROPOSED_JE_DRAFTED,
        "BUDGET_OVERAGE_RISK": Channel.IMPACT_ADVISORY_BUDGET_THRESHOLD,
        "FUND_RESTRICTION_VIOLATION": Channel.IMPACT_ADVISORY_RESTRICTION_REJECTED,
        "POLICY_VIOLATION": Channel.IMPACT_PROPOSED_JE_DRAFTED,
        "JOURNAL_ENTRY_READY": Channel.IMPACT_PROPOSED_JE_DRAFTED,
    }

    # Get perturbation metadata from registry
    try:
        perturbation = get_perturbation(signal_name)
    except (KeyError, Exception):
        perturbation = None

    signal = ImpactSignal(
        signal_id=perturbation.id if perturbation else 59,
        signal_name=signal_name,
        event_id=f"eval-{job.job_id}-{uuid4().hex[:8]}",
        occurred_at=job.updated_at or datetime.utcnow(),
        privacy_class=perturbation.privacy_class if perturbation else "P1",  # type: ignore[arg-type]
        crosses_membrane=perturbation.crosses_membrane if perturbation else True,
        target_channel=channel_map.get(signal_name, Channel.IMPACT_PROPOSED_INVOICE_INGESTED),
        payload={
            "job_id": job.job_id,
            "church_id": job.church_id,
            "document_type": job.document_type.value if hasattr(job, "document_type") and job.document_type else "INVOICE",
        },
        source="phase8-approval-integration",
    )
    return signal
