"""Phase 14: GL Trace — Event-Sourced GL Drill-Down.

Implements GET /api/trace/{cell_id} endpoint.
Returns Signal Memory cards contributing to a GL cell's current balance.
"""

import logging
from typing import Dict, Any, List

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def get_gl_trace(
    cell_id: str,
    include_lineage: bool = True,
) -> Dict[str, Any]:
    """Get trace of events contributing to a GL cell.

    Args:
        cell_id: GL cell ID (e.g., "41000" for expense account)
        include_lineage: Include full provenance chain

    Returns:
        Dict with:
        - cell_id: The GL cell
        - current_balance: Current balance
        - signal_memory: List of Signal Memory cards affecting this cell
        - lineage: Provenance chain if requested
    """
    card_store = get_card_store()

    # Query all Memory Cards (signals that affected GL)
    all_cards = card_store.query_by_principal("distiller")

    # Filter cards affecting this cell
    affecting_cards = []
    for card in all_cards:
        # Check if card has GL impact for this cell
        gl_impact = card.get("gl_impact", {})
        if isinstance(gl_impact, dict) and cell_id in gl_impact:
            affecting_cards.append(card)

    # Also check Cabinet outputs (decisions, projections) that might affect this cell
    decision_cards = card_store.query_by_principal("decision-deputy")
    for card in decision_cards:
        if _card_affects_cell(card, cell_id):
            affecting_cards.append(card)

    # Sort by created_at to show chronological order
    affecting_cards.sort(key=lambda c: c.get("created_at", ""), reverse=False)

    # Calculate current balance by summing impacts
    current_balance = sum(
        float(card.get("gl_impact", {}).get(cell_id, 0))
        for card in affecting_cards
        if isinstance(card.get("gl_impact", {}), dict)
    )

    return {
        "cell_id": cell_id,
        "current_balance": current_balance,
        "signal_count": len(affecting_cards),
        "signals": [_format_signal_card(card) for card in affecting_cards],
        "lineage": _build_lineage(affecting_cards) if include_lineage else None,
    }


def _card_affects_cell(card: Dict[str, Any], cell_id: str) -> bool:
    """Check if card affects a GL cell."""
    # Decision cards with GL impact
    gl_impact = card.get("gl_impact")
    if gl_impact and isinstance(gl_impact, dict) and cell_id in gl_impact:
        return True

    # Cards with affected_accounts
    affected = card.get("affected_accounts", [])
    if cell_id in affected:
        return True

    return False


def _format_signal_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Format a signal card for trace output."""
    return {
        "card_id": card.get("card_id"),
        "card_type": card.get("card_type"),
        "principal": card.get("principal"),
        "created_at": card.get("created_at"),
        "content": card.get("content", ""),
        "gl_impact": card.get("gl_impact", {}),
        "confidence": card.get("confidence"),
        "hash": card.get("_hash"),
    }


def _build_lineage(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build provenance lineage for cards."""
    return {
        "total_cards": len(cards),
        "by_principal": _group_by_principal(cards),
        "by_type": _group_by_type(cards),
    }


def _group_by_principal(cards: List[Dict[str, Any]]) -> Dict[str, int]:
    """Group cards by principal."""
    groups = {}
    for card in cards:
        principal = card.get("principal", "unknown")
        groups[principal] = groups.get(principal, 0) + 1
    return groups


def _group_by_type(cards: List[Dict[str, Any]]) -> Dict[str, int]:
    """Group cards by type."""
    groups = {}
    for card in cards:
        card_type = card.get("card_type", "unknown")
        groups[card_type] = groups.get(card_type, 0) + 1
    return groups
