"""Phase 17: Pledge Matching — Pledge-to-Cash Reconciliation.

Match pledges/commitments against receipts and track fulfillment.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional

from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def create_pledge(
    pledge_id: str,
    donor_name: str,
    amount: Decimal,
    purpose: str,
    pledge_date: str,
    expected_receipt_date: Optional[str] = None,
    restrictions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new pledge record.

    Args:
        pledge_id: Unique pledge identifier
        donor_name: Name of pledging donor/entity
        amount: Pledge amount
        purpose: Intended use/purpose
        pledge_date: Date pledge was made (ISO format)
        expected_receipt_date: Expected date of cash receipt
        restrictions: Optional use restrictions

    Returns:
        Pledge card with ID and metadata
    """
    from backend.cards.schemas import MemoryCard

    card_store = get_card_store()

    pledge_card = MemoryCard(
        card_id=f"pledge-{pledge_id}",
        principal="intake-specialist",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Pledge from {donor_name}: ${amount} for {purpose}",
        confidence=0.95,
    )

    # Store pledge metadata
    pledge_data = {
        "pledge_id": pledge_id,
        "donor_name": donor_name,
        "amount": float(amount),
        "purpose": purpose,
        "pledge_date": pledge_date,
        "expected_receipt_date": expected_receipt_date,
        "restrictions": restrictions or {},
        "status": "pending",
        "matched_receipts": [],
        "fulfillment_pct": 0.0,
    }

    card_store.write(pledge_card, chain=True)

    return pledge_data


async def match_pledge_to_receipt(
    pledge_id: str,
    receipt_amount: Decimal,
    receipt_date: str,
    invoice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Match received cash to a pledge.

    Args:
        pledge_id: Pledge identifier
        receipt_amount: Amount received
        receipt_date: Date amount received
        invoice_id: Optional invoice/receipt reference

    Returns:
        Match record with pledge-to-cash link
    """
    from backend.cards.schemas import MemoryCard

    card_store = get_card_store()

    # Create match record
    match_card = MemoryCard(
        card_id=f"pledge-match-{pledge_id}-{receipt_date}",
        principal="decision-deputy",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Matched ${receipt_amount} to pledge {pledge_id}",
        confidence=0.90,
    )

    match_data = {
        "pledge_id": pledge_id,
        "receipt_amount": float(receipt_amount),
        "receipt_date": receipt_date,
        "invoice_id": invoice_id,
        "match_status": "matched",
        "timestamp": datetime.utcnow().isoformat(),
    }

    card_store.write(match_card, chain=True)

    return match_data


async def get_pledge_fulfillment(
    pledge_id: str,
) -> Dict[str, Any]:
    """Get pledge fulfillment status and matching.

    Args:
        pledge_id: Pledge identifier

    Returns:
        Fulfillment summary with matched amounts and gap analysis
    """
    card_store = get_card_store()

    # Query pledge and matches
    all_cards = card_store.query_by_principal("intake-specialist")
    pledge_cards = [c for c in all_cards if pledge_id in str(c.get("card_id"))]

    if not pledge_cards:
        return {
            "pledge_id": pledge_id,
            "status": "not_found",
            "fulfillment_pct": 0.0,
            "matched_amount": 0.0,
            "outstanding": 0.0,
        }

    # Extract pledge amount (would normally be from stored metadata)
    pledge_amount = Decimal("10000")  # Placeholder

    # Get matches
    match_cards = card_store.query_by_principal("decision-deputy")
    pledge_matches = [
        m for m in match_cards
        if pledge_id in str(m.get("content", ""))
    ]

    matched_total = sum(
        Decimal(str(m.get("amount", 0)))
        for m in pledge_matches
    )

    fulfillment_pct = float(matched_total / pledge_amount * 100) if pledge_amount else 0

    return {
        "pledge_id": pledge_id,
        "pledge_amount": float(pledge_amount),
        "matched_amount": float(matched_total),
        "outstanding": float(pledge_amount - matched_total),
        "fulfillment_pct": fulfillment_pct,
        "match_count": len(pledge_matches),
        "status": "fulfilled" if fulfillment_pct >= 100 else "pending",
    }


async def list_pledges(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List pledges with optional filtering.

    Args:
        status: Optional status filter (pending, fulfilled, overdue)
        limit: Number of results to return
        offset: Pagination offset

    Returns:
        List of pledges with pagination
    """
    card_store = get_card_store()

    # Query pledges
    all_cards = card_store.query_by_principal("intake-specialist")
    pledge_cards = [c for c in all_cards if "pledge" in str(c.get("card_id", "")).lower()]

    # Filter by status if specified
    if status:
        pledge_cards = [p for p in pledge_cards if _get_pledge_status(p) == status]

    total = len(pledge_cards)
    pledges = pledge_cards[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "pledges": [
            {
                "pledge_id": c.get("card_id"),
                "content": c.get("content"),
                "created_at": c.get("created_at"),
            }
            for c in pledges
        ],
    }


# ===== Helper Functions =====


def _get_pledge_status(pledge_card: Dict[str, Any]) -> str:
    """Get pledge status from card."""
    created_at = pledge_card.get("created_at")
    if isinstance(created_at, str):
        try:
            pledge_date = datetime.fromisoformat(created_at)
            if datetime.utcnow() - pledge_date > timedelta(days=365):
                return "overdue"
        except (ValueError, AttributeError):
            pass

    # Would check fulfillment percentage from card data
    return "pending"
