"""Phase 19: Continuous Compliance Monitoring.

Validates transactions against stored policies and compliance rules.
Delegates core evaluation to policy_management to avoid duplicate logic.
"""
import logging
from datetime import datetime
from typing import Dict, Any

from backend.cards.store import get_card_store
from backend.membrane.pledge.policy_management import (
    check_policy_compliance as _evaluate_policy_compliance,
)

logger = logging.getLogger(__name__)


async def check_continuous_compliance(
    transaction_amount: float,
    account: str,
    department: str,
    transaction_type: str = "general",
) -> Dict[str, Any]:
    """Check real-time policy compliance against stored policies.

    Delegates to policy_management.check_policy_compliance — single source of truth.
    """
    result = await _evaluate_policy_compliance(
        transaction_amount=transaction_amount,
        account=account,
        department=department,
        transaction_type=transaction_type,
    )
    result["transaction_amount"] = transaction_amount
    return result


async def get_compliance_report(
    period: str = "weekly",
) -> Dict[str, Any]:
    """Get compliance summary report from Card Store violation records."""
    card_store = get_card_store()

    all_violations = []

    for principal in ["policy-engine", "audit-engine", "compliance-engine"]:
        violation_cards = card_store.query_by_principal(principal)
        all_violations.extend(
            v for v in violation_cards
            if v.get("metadata", {}).get("is_violation", False)
        )

    violation_types: Dict[str, int] = {}
    for violation in all_violations:
        vtype = violation.get("metadata", {}).get("violation_type", "unknown")
        violation_types[vtype] = violation_types.get(vtype, 0) + 1

    blocked = sum(
        1 for v in all_violations
        if v.get("metadata", {}).get("severity") == "blocked"
    )
    warnings = len(all_violations) - blocked

    # Count total transactions checked (cards tagged as compliance_checked)
    all_checked = card_store.query_by_metadata("compliance_checked", True)
    total_checked = len(all_checked) if all_checked else None

    if total_checked:
        compliance_rate = 100.0 * (total_checked - len(all_violations)) / total_checked
    else:
        # Cannot compute rate without total transaction count; report raw violation count
        compliance_rate = None

    return {
        "period": period,
        "total_violations": len(all_violations),
        "blocked_transactions": blocked,
        "warning_transactions": warnings,
        "compliance_rate": compliance_rate,
        "compliance_rate_note": (
            None if compliance_rate is not None
            else "Rate unavailable: total transaction count not tracked"
        ),
        "top_violation_types": [
            {"type": vtype, "count": count}
            for vtype, count in sorted(violation_types.items(), key=lambda x: -x[1])[:3]
        ],
        "generated_at": datetime.utcnow().isoformat(),
    }


async def auto_repair_exception(
    exception_id: str,
) -> Dict[str, Any]:
    """Auto-repair reconciliation exception.

    NOT YET IMPLEMENTED — returns a pending status so callers know no repair occurred.
    Implement: look up the exception card, apply matching heuristics, write a resolution card.
    """
    logger.warning("auto_repair_exception called for %s but repair logic is not implemented", exception_id)
    return {
        "exception_id": exception_id,
        "status": "pending",
        "repair_method": None,
        "message": "Auto-repair not yet implemented. Manual review required.",
        "attempted_at": datetime.utcnow().isoformat(),
    }
