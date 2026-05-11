"""Phase 14: Forecast Merge — GL Projection Waterfall.

Implements GET /api/forecast/merge endpoint.
Returns delta between two GL projection snapshots.
"""

import logging
from typing import Dict, Any, Optional
from decimal import Decimal

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def get_forecast_merge(
    from_date: str,
    to_date: str,
) -> Dict[str, Any]:
    """Get GL projection waterfall between two dates.

    Args:
        from_date: Start date (ISO format, e.g., "2026-04-30")
        to_date: End date (ISO format, e.g., "2026-05-11")

    Returns:
        Dict with:
        - from_snapshot: GL at from_date
        - to_snapshot: GL at to_date
        - delta: Changes per account
        - waterfall: Step-by-step changes with drivers
    """
    card_store = get_card_store()

    # Query Plan Cards (GL snapshots) from Card Store
    all_plans = card_store.query_by_principal("budget-steward")

    # Filter by date range
    from_snapshot = _find_snapshot_at_or_before(all_plans, from_date)
    to_snapshot = _find_snapshot_at_or_before(all_plans, to_date)

    if not from_snapshot or not to_snapshot:
        logger.warning(f"Missing snapshots for date range {from_date}..{to_date}")
        return {
            "from_date": from_date,
            "to_date": to_date,
            "error": "Insufficient snapshot data",
        }

    # Calculate delta
    delta = _calculate_delta(from_snapshot, to_snapshot)

    # Build waterfall explaining changes
    waterfall = _build_waterfall(
        from_snapshot,
        to_snapshot,
        from_date,
        to_date,
    )

    return {
        "from_date": from_date,
        "to_date": to_date,
        "from_snapshot": from_snapshot,
        "to_snapshot": to_snapshot,
        "delta": delta,
        "waterfall": waterfall,
    }


def _find_snapshot_at_or_before(
    snapshots: list[Dict[str, Any]],
    target_date: str,
) -> Optional[Dict[str, Any]]:
    """Find the most recent snapshot at or before target date."""
    matching = []
    for snapshot in snapshots:
        snapshot_date = snapshot.get("created_at", "")
        if isinstance(snapshot_date, str) and snapshot_date <= target_date:
            matching.append(snapshot)

    if not matching:
        return None

    # Return most recent
    matching.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return matching[0]


def _calculate_delta(
    from_snapshot: Dict[str, Any],
    to_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate account-by-account changes."""
    from_accounts = from_snapshot.get("accounts", from_snapshot.get("gl_accounts", {}))
    to_accounts = to_snapshot.get("accounts", to_snapshot.get("gl_accounts", {}))

    delta = {}
    all_accounts = set(from_accounts.keys()) | set(to_accounts.keys())

    for account in all_accounts:
        from_val = Decimal(str(from_accounts.get(account, 0)))
        to_val = Decimal(str(to_accounts.get(account, 0)))
        change = to_val - from_val

        if change != 0:
            delta[account] = {
                "from": float(from_val),
                "to": float(to_val),
                "change": float(change),
                "pct_change": (
                    float((change / from_val * 100))
                    if from_val != 0
                    else None
                ),
            }

    return delta


def _build_waterfall(
    from_snapshot: Dict[str, Any],
    to_snapshot: Dict[str, Any],
    from_date: str,
    to_date: str,
) -> Dict[str, Any]:
    """Build waterfall explanation of changes."""
    # For now, return simplified waterfall
    # In production, would trace signals/decisions that caused changes

    from_accounts = from_snapshot.get("accounts", from_snapshot.get("gl_accounts", {}))
    to_accounts = to_snapshot.get("accounts", to_snapshot.get("gl_accounts", {}))

    total_from = sum(
        float(v) for v in from_accounts.values()
        if isinstance(v, (int, float, Decimal))
    )
    total_to = sum(
        float(v) for v in to_accounts.values()
        if isinstance(v, (int, float, Decimal))
    )

    return {
        "starting_balance": float(total_from),
        "ending_balance": float(total_to),
        "net_change": float(total_to - total_from),
        "period": f"{from_date}..{to_date}",
        "drivers": _extract_drivers(from_snapshot, to_snapshot),
    }


def _extract_drivers(
    from_snapshot: Dict[str, Any],
    to_snapshot: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Extract key drivers of GL changes."""
    # Query for signals/decisions that caused changes
    # For now, return empty list (full integration in Phase 20)
    return []
