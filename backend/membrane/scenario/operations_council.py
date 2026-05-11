"""Phase 15: Operations Council — Real-Time KPI Dashboard.

Aggregates queue metrics, policy violations, budget variance, and operational status
for real-time governance oversight by the Operations Council.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List

from backend.cards.store import get_card_store
from backend.cards.schemas import CardType

logger = logging.getLogger(__name__)


async def get_council_kpis(
    period_days: int = 7,
    breakdown_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Get Operations Council KPI dashboard.

    Args:
        period_days: Number of days to look back (default 7 = weekly)
        breakdown_by: Optional breakdown dimension (department, cost_center, fund, etc.)

    Returns:
        Dict with:
        - exception_volume: Total exceptions in period + trend
        - policy_violations: Violation count + breakdown
        - budget_variance: Net GL variance + by department
        - queue_status: Current queue health (backlog, aging)
        - risk_score: Overall operational risk assessment
    """
    card_store = get_card_store()
    now = datetime.utcnow()
    period_start = now - timedelta(days=period_days)

    # Query all signals (exceptions, violations, budget items) from period
    all_signals = card_store.query_by_principal("distiller")
    period_start_str = period_start.isoformat()
    signals_in_period = [
        s for s in all_signals
        if (s.get("created_at") and
            isinstance(s.get("created_at"), str) and
            str(s.get("created_at")) >= period_start_str)
    ]

    # Count exception types
    exception_count = sum(
        1 for s in signals_in_period
        if s.get("content") and "exception" in s.get("content", "").lower()
    )

    # Count policy violations
    violation_count = sum(
        1 for s in signals_in_period
        if s.get("content") and "policy" in s.get("content", "").lower()
    )

    # Get latest GL snapshot for budget variance calculation
    plan_cards = card_store.query_by_principal("budget-steward")
    if not plan_cards:
        plan_cards = []

    # Estimate GL totals from most recent plan
    current_gl = {}
    if plan_cards:
        latest_plan = plan_cards[-1]
        current_gl = latest_plan.get("accounts", {})

    # Calculate budget variance (sum of all GL cells)
    total_gl = sum(
        Decimal(str(v)) for v in current_gl.values()
        if isinstance(v, (int, float, Decimal))
    )

    # Ensure total_gl is Decimal
    total_gl_decimal = Decimal(str(total_gl)) if total_gl else Decimal("0")

    # Build KPI response
    kpis = {
        "timestamp": now.isoformat(),
        "period_days": period_days,
        "exception_metrics": {
            "total_count": exception_count,
            "trend": "stable",  # Would analyze vs prior period
            "flagged_for_review": max(0, exception_count - 5),  # Threshold at 5
            "aging_exceptions": _count_aging_exceptions(signals_in_period),
        },
        "policy_violations": {
            "total_count": violation_count,
            "by_type": _categorize_violations(signals_in_period),
            "critical": max(0, violation_count - 2),  # Critical if > 2
        },
        "budget_metrics": {
            "total_gl": float(total_gl),
            "variance_threshold_exceeded": violation_count > 0,
            "net_variance": _calculate_net_variance(current_gl),
            "cells_at_risk": _find_variance_cells(current_gl),
        },
        "queue_health": {
            "exceptions_awaiting_review": exception_count,
            "escalations_pending": max(0, violation_count),
            "avg_resolution_time_hours": _estimate_resolution_time(signals_in_period),
        },
        "operational_risk_score": _calculate_risk_score(
            exception_count,
            violation_count,
            total_gl_decimal,
        ),
    }

    if breakdown_by:
        kpis["breakdown"] = _breakdown_by_dimension(
            breakdown_by,
            signals_in_period,
            current_gl,
        )

    return kpis


async def get_queue_status() -> Dict[str, Any]:
    """Get current queue status snapshot.

    Returns:
        Dict with queue counts by type (exceptions, questions, policies, recommendations).
    """
    card_store = get_card_store()

    # Count exceptions (signals tagged as exceptions)
    all_signals = card_store.query_by_principal("distiller")
    exceptions = [
        s for s in all_signals
        if s.get("content") and "exception" in s.get("content", "").lower()
    ]

    # Count policy violations
    violations = [
        s for s in all_signals
        if s.get("content") and "policy" in s.get("content", "").lower()
    ]

    # Count questions (card_type == "question")
    decision_cards = card_store.query_by_principal("decision-deputy")
    questions = [
        c for c in decision_cards
        if c.get("card_type") == CardType.QUESTION.value
    ]

    # Count recommendations (card_type == "recommendation")
    nba_cards = card_store.query_by_principal("nba-crew")
    recommendations = [
        c for c in nba_cards
        if c.get("card_type") == CardType.RECOMMENDATION.value
    ]

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "exceptions": {
            "total": len(exceptions),
            "critical": len([e for e in exceptions if _is_critical(e)]),
            "aging": len([e for e in exceptions if _is_aging(e)]),
        },
        "policy_violations": {
            "total": len(violations),
            "pending_review": len([v for v in violations if not _is_resolved(v)]),
        },
        "questions_pending": len(questions),
        "recommendations": {
            "total": len(recommendations),
            "pending_approval": len([r for r in recommendations if _is_pending(r)]),
        },
    }


# ===== Helper Functions =====


def _count_aging_exceptions(signals: List[Dict[str, Any]]) -> int:
    """Count exceptions older than 24 hours."""
    now = datetime.utcnow()
    aging = 0
    for signal in signals:
        if signal.get("created_at") and isinstance(signal.get("created_at"), str):
            try:
                created = datetime.fromisoformat(signal["created_at"].replace("Z", "+00:00"))
                if now - created > timedelta(hours=24):
                    aging += 1
            except (ValueError, AttributeError):
                pass
    return aging


def _categorize_violations(signals: List[Dict[str, Any]]) -> Dict[str, int]:
    """Categorize policy violations by type."""
    categories = {}
    for signal in signals:
        content = signal.get("content", "").lower()
        if "budget" in content:
            categories["budget_overage"] = categories.get("budget_overage", 0) + 1
        elif "fund" in content:
            categories["fund_restriction"] = categories.get("fund_restriction", 0) + 1
        elif "approval" in content:
            categories["missing_approval"] = categories.get("missing_approval", 0) + 1
        else:
            categories["other"] = categories.get("other", 0) + 1
    return categories


def _calculate_net_variance(current_gl: Dict[str, Any]) -> float:
    """Calculate net GL variance (total of all accounts)."""
    return float(
        sum(
            Decimal(str(v)) for v in current_gl.values()
            if isinstance(v, (int, float, Decimal))
        )
    )


def _find_variance_cells(current_gl: Dict[str, Any]) -> List[str]:
    """Find GL cells exceeding variance threshold."""
    threshold = Decimal("1000")  # $1000 variance threshold per cell
    at_risk = []
    for account, value in current_gl.items():
        try:
            val = Decimal(str(value))
            if abs(val) > threshold:
                at_risk.append(account)
        except (ValueError, TypeError):
            pass
    return at_risk


def _estimate_resolution_time(signals: List[Dict[str, Any]]) -> float:
    """Estimate average resolution time (hours)."""
    # Placeholder: would calculate from exception timestamps and resolution records
    # For now, return estimated baseline of 4 hours
    return 4.0


def _calculate_risk_score(
    exception_count: int,
    violation_count: int,
    total_gl: Decimal,
) -> str:
    """Calculate operational risk score (low/medium/high)."""
    # Risk scoring: exceptions + violations indicate operational risk
    score = exception_count + (violation_count * 2)

    if score <= 5:
        return "low"
    elif score <= 15:
        return "medium"
    else:
        return "high"


def _breakdown_by_dimension(
    dimension: str,
    signals: List[Dict[str, Any]],
    current_gl: Dict[str, Any],
) -> Dict[str, Any]:
    """Break down KPIs by dimension (department, cost_center, fund, etc.)."""
    # Placeholder: would parse signals to extract dimension metadata
    # Return empty breakdown for now
    return {
        dimension: {
            "total_exceptions": 0,
            "total_violations": 0,
            "gl_variance": 0,
        }
    }


def _is_critical(exception: Dict[str, Any]) -> bool:
    """Check if exception is critical."""
    content = exception.get("content", "").lower()
    return "critical" in content or "urgent" in content


def _is_aging(exception: Dict[str, Any]) -> bool:
    """Check if exception is aging (24+ hours old)."""
    if exception.get("created_at") and isinstance(exception.get("created_at"), str):
        try:
            created = datetime.fromisoformat(
                exception["created_at"].replace("Z", "+00:00")
            )
            return datetime.utcnow() - created > timedelta(hours=24)
        except (ValueError, AttributeError):
            return False
    return False


def _is_resolved(violation: Dict[str, Any]) -> bool:
    """Check if violation is marked resolved."""
    return violation.get("resolved_at") is not None or violation.get("status") == "resolved"


def _is_pending(recommendation: Dict[str, Any]) -> bool:
    """Check if recommendation is pending approval."""
    return recommendation.get("status") in ("draft", "pending", None)
