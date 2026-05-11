"""Store for recurring JE tolerance learning (Flow 17 - learning loop)."""
from typing import Optional, Dict, Any, cast
from datetime import datetime
from .connection import execute_query


def record_tolerance_feedback(
    recurring_id: str,
    accepted: bool,
    current_tolerance_low: float,
    current_tolerance_high: float,
) -> None:
    """Record user acceptance/rejection feedback for a recurring JE."""
    # Check if existing record exists
    existing = cast(Optional[Dict[str, Any]], execute_query(
        """SELECT id FROM recurring_tolerance_history
           WHERE recurring_id = %s
           ORDER BY created_at DESC
           LIMIT 1""",
        (recurring_id,),
        fetch_one=True
    ))

    if existing:
        # Update acceptance/rejection counts
        col_name = "acceptance_count" if accepted else "rejection_count"
        execute_query(
            f"UPDATE recurring_tolerance_history SET {col_name} = {col_name} + 1 WHERE id = %s",
            (existing.get('id'),)
        )
    else:
        # Create initial record
        execute_query(
            """INSERT INTO recurring_tolerance_history
               (recurring_id, tolerance_low, tolerance_high, acceptance_count, rejection_count, created_at)
               VALUES (%s, %s, %s, %s, %s, NOW())""",
            (recurring_id, current_tolerance_low, current_tolerance_high,
             1 if accepted else 0, 0 if accepted else 1)
        )


def get_tolerance_bounds(recurring_id: str) -> Optional[Dict[str, Any]]:
    """Get current acceptance/rejection feedback for a recurring JE."""
    row = cast(Optional[Dict[str, Any]], execute_query(
        """SELECT tolerance_low, tolerance_high, acceptance_count, rejection_count, last_adjusted_at
           FROM recurring_tolerance_history
           WHERE recurring_id = %s
           ORDER BY created_at DESC
           LIMIT 1""",
        (recurring_id,),
        fetch_one=True
    ))

    if not row:
        return None

    acceptance_count = row.get('acceptance_count', 0) or 0
    rejection_count = row.get('rejection_count', 0) or 0
    total = acceptance_count + rejection_count

    last_adjusted = row.get('last_adjusted_at')
    return {
        "tolerance_low": float(row.get('tolerance_low', 0)),
        "tolerance_high": float(row.get('tolerance_high', 0)),
        "acceptance_count": acceptance_count,
        "rejection_count": rejection_count,
        "last_adjusted_at": last_adjusted.isoformat() if last_adjusted else None,
        "acceptance_rate": (
            acceptance_count / total if total > 0 else 0.5
        ),
    }


def adjust_tolerance_bounds(
    recurring_id: str,
    new_tolerance_low: float,
    new_tolerance_high: float,
    adjusted_by: str = "FEEDBACK_ENGINE",
    rationale: str = "",
) -> None:
    """Adjust tolerance bounds based on feedback pattern."""
    execute_query(
        """INSERT INTO recurring_tolerance_history
           (recurring_id, tolerance_low, tolerance_high, last_adjusted_at, adjusted_by, rationale, created_at)
           VALUES (%s, %s, %s, NOW(), %s, %s, NOW())""",
        (recurring_id, new_tolerance_low, new_tolerance_high, adjusted_by, rationale)
    )


def should_auto_post(
    recurring_id: str,
    proposed_amount: float,
) -> Dict[str, Any]:
    """
    Check if a proposed amount should auto-post based on tolerance bounds.
    Returns decision + bounds info for UI visibility.
    """
    bounds = get_tolerance_bounds(recurring_id)

    if not bounds:
        # No history yet; default to not auto-posting
        return {
            "should_auto_post": False,
            "reason": "No tolerance history",
            "bounds": None,
        }

    low = bounds["tolerance_low"]
    high = bounds["tolerance_high"]
    auto_post = low <= proposed_amount <= high

    return {
        "should_auto_post": auto_post,
        "reason": f"Amount {proposed_amount} is {'within' if auto_post else 'outside'} tolerance bounds [{low}, {high}]",
        "bounds": {
            "low": low,
            "high": high,
            "acceptance_rate": bounds["acceptance_rate"],
            "feedback_count": bounds["acceptance_count"] + bounds["rejection_count"],
        },
    }
