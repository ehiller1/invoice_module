"""Phase 17: Pledge Matching — Pledge-to-Cash Reconciliation.

Match pledges/commitments against receipts and track fulfillment.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
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
    validate_id_component(pledge_id, field="pledge_id")
    card_store = get_card_store()

    pledge_card = MemoryCard(
        card_id=f"pledge-{pledge_id}",
        principal="pledge-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Pledge from {donor_name}: ${amount} for {purpose}",
        confidence=0.95,
        metadata={
            "pledge_id": pledge_id,
            "donor_name": donor_name,
            "amount": float(amount),
            "purpose": purpose,
            "pledge_date": pledge_date,
            "expected_receipt_date": expected_receipt_date,
            "restrictions": restrictions or {},
        },
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
    validate_id_component(pledge_id, field="pledge_id")
    card_store = get_card_store()

    match_data = {
        "pledge_id": pledge_id,
        "receipt_amount": float(receipt_amount),
        "receipt_date": receipt_date,
        "invoice_id": invoice_id,
        "match_status": "matched",
        "timestamp": datetime.utcnow().isoformat(),
    }

    match_card = MemoryCard(
        card_id=f"pledge-match-{pledge_id}-{receipt_date}",
        principal="pledge-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Matched ${receipt_amount} to pledge {pledge_id}",
        confidence=0.90,
        metadata=match_data,
    )

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

    # Query pledge record
    pledge_card = card_store.read(f"pledge-{pledge_id}")

    if not pledge_card:
        return {
            "pledge_id": pledge_id,
            "status": "not_found",
            "fulfillment_pct": 0.0,
            "matched_amount": 0.0,
            "outstanding": 0.0,
        }

    # Extract pledge amount from metadata
    metadata = pledge_card.get("metadata", {})
    pledge_amount = Decimal(str(metadata.get("amount", 0)))

    if pledge_amount == 0:
        return {
            "pledge_id": pledge_id,
            "status": "invalid",
            "fulfillment_pct": 0.0,
            "matched_amount": 0.0,
            "outstanding": 0.0,
        }

    # Get match cards for this pledge (card_id prefix: pledge-match-{pledge_id}-)
    match_cards = card_store.query_by_principal("pledge-engine")
    pledge_matches = [
        m for m in match_cards
        if str(m.get("card_id", "")).startswith(f"pledge-match-{pledge_id}-")
    ]

    matched_total = sum(
        Decimal(str(m.get("metadata", {}).get("receipt_amount", 0)))
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

    # Query pledges (exclude match records like "pledge-match-...")
    all_cards = card_store.query_by_principal("pledge-engine")
    pledge_cards = [
        c for c in all_cards
        if str(c.get("card_id", "")).startswith("pledge-")
        and not str(c.get("card_id", "")).startswith("pledge-match-")
    ]

    # Filter by status if specified (requires per-pledge fulfillment check)
    if status:
        filtered = []
        for p in pledge_cards:
            pledge_id = p.get("metadata", {}).get("pledge_id")
            if not pledge_id:
                continue
            pledge_status = await _resolve_pledge_status(p, pledge_id)
            if pledge_status == status:
                filtered.append(p)
        pledge_cards = filtered

    total = len(pledge_cards)
    pledges = pledge_cards[offset : offset + limit]

    pledges_out = []
    for c in pledges:
        meta = c.get("metadata", {})
        pid = meta.get("pledge_id") or c.get("card_id", "").replace("pledge-", "")
        pledges_out.append({
            "pledge_id": pid,
            "donor_name": meta.get("donor_name"),
            "amount": meta.get("amount"),
            "purpose": meta.get("purpose"),
            "pledge_date": meta.get("pledge_date"),
            "expected_receipt_date": meta.get("expected_receipt_date"),
            "status": await _resolve_pledge_status(c, pid),
            "created_at": c.get("created_at"),
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "pledges": pledges_out,
    }


# ===== Helper Functions =====


async def _resolve_pledge_status(pledge_card: Dict[str, Any], pledge_id: str) -> str:
    """Resolve pledge status from fulfillment percentage and expected_receipt_date.

    Returns one of: "fulfilled", "overdue", "pending".
    """
    fulfillment = await get_pledge_fulfillment(pledge_id)
    if fulfillment.get("fulfillment_pct", 0.0) >= 100.0:
        return "fulfilled"

    meta = pledge_card.get("metadata", {})
    expected = meta.get("expected_receipt_date")
    if expected:
        try:
            expected_dt = datetime.fromisoformat(expected)
            if datetime.utcnow() > expected_dt:
                return "overdue"
        except (ValueError, AttributeError):
            pass

    return "pending"
