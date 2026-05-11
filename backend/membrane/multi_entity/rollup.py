"""Phase 16: GL Consolidation Rollup.

Multi-entity and multi-location GL consolidation with adjustment tracking.
"""

import logging
from decimal import Decimal
from typing import Dict, Any, List, Optional

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def get_entity_glaccounts(
    entity_id: str,
) -> Dict[str, Decimal]:
    """Get GL accounts for a specific entity.

    Args:
        entity_id: Entity identifier (subsidiary, location, cost center)

    Returns:
        Dict of {account: balance}
    """
    card_store = get_card_store()

    # Query Plan Cards tagged with entity
    all_plans = card_store.query_by_principal("budget-steward")
    entity_plans = [
        p for p in all_plans
        if p.get("assumptions", {}).get("entity_id") == entity_id
        or entity_id in str(p.get("accounts", {}))
    ]

    if not entity_plans:
        return {}

    # Get latest plan for entity
    latest = entity_plans[-1]
    accounts = latest.get("accounts", {})

    return {k: Decimal(str(v)) for k, v in accounts.items()}


async def consolidate_entities(
    entity_ids: Optional[List[str]] = None,
    include_adjustments: bool = True,
) -> Dict[str, Any]:
    """Consolidate GL across multiple entities.

    Args:
        entity_ids: List of entity IDs to consolidate. If None, consolidate all.
        include_adjustments: Whether to include consolidation adjustments

    Returns:
        Dict with:
        - consolidated_gl: Rolled-up GL accounts
        - by_entity: GL breakdown by entity
        - adjustments: Consolidation adjustments (if requested)
        - elimination_entries: Intercompany eliminations
    """
    card_store = get_card_store()

    # Get all entity GL
    all_plans = card_store.query_by_principal("budget-steward")
    if not all_plans:
        return {
            "consolidated_gl": {},
            "by_entity": {},
            "adjustments": [],
            "elimination_entries": [],
        }

    # Group by entity
    by_entity = {}
    for plan in all_plans:
        assumptions = plan.get("assumptions", {})
        entity_id = assumptions.get("entity_id", "default")

        if entity_ids and entity_id not in entity_ids:
            continue

        accounts = plan.get("accounts", {})
        by_entity[entity_id] = {k: Decimal(str(v)) for k, v in accounts.items()}

    # Roll up GL accounts
    consolidated_gl = _rollup_accounts(by_entity)

    # Calculate adjustments
    adjustments = []
    if include_adjustments:
        adjustments = _calculate_adjustments(by_entity, consolidated_gl)

    # Extract elimination entries
    elimination_entries = _identify_eliminations(by_entity)

    return {
        "consolidated_gl": {k: float(v) for k, v in consolidated_gl.items()},
        "by_entity": {
            entity: {k: float(v) for k, v in gl.items()}
            for entity, gl in by_entity.items()
        },
        "adjustments": adjustments,
        "elimination_entries": elimination_entries,
    }


async def get_consolidation_adjustments(
    from_entity_id: str,
    to_entity_id: str,
) -> Dict[str, Any]:
    """Get consolidation adjustments between entities.

    Args:
        from_entity_id: Source entity
        to_entity_id: Target entity

    Returns:
        Dict with adjustment transactions for consolidation
    """
    # Placeholder: would query for intercompany transactions
    # and generate consolidation entries

    return {
        "adjustments": [
            {
                "account": "10000",  # Intercompany receivable
                "entity": from_entity_id,
                "amount": 0,  # Would be calculated from actual intercompany balances
                "type": "elimination",
            }
        ],
        "elimination_basis": "reciprocal_method",  # or "gross_method"
    }


# ===== Helper Functions =====


def _rollup_accounts(by_entity: Dict[str, Dict[str, Decimal]]) -> Dict[str, Decimal]:
    """Roll up accounts across entities."""
    consolidated = {}

    for entity_gl in by_entity.values():
        for account, amount in entity_gl.items():
            if account not in consolidated:
                consolidated[account] = Decimal("0")
            consolidated[account] += Decimal(str(amount))

    return consolidated


def _calculate_adjustments(
    by_entity: Dict[str, Dict[str, Decimal]],
    consolidated_gl: Dict[str, Decimal],
) -> List[Dict[str, Any]]:
    """Calculate consolidation adjustments."""
    adjustments = []

    # Placeholder: would identify intercompany eliminations
    # and other consolidation adjustments (equity pickup, etc.)

    return adjustments


def _identify_eliminations(by_entity: Dict[str, Dict[str, Decimal]]) -> List[Dict[str, Any]]:
    """Identify intercompany transactions for elimination."""
    eliminations = []

    # Placeholder: would scan for reciprocal accounts
    # (e.g., receivable in one entity, payable in another)
    # and create elimination entries

    return eliminations
