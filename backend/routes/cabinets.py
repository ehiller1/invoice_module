"""Phase 12: Cabinet Activity Endpoints.

Back the cabinet.html UI with real cabinet activity, decision approvals,
and status updates.
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from datetime import datetime

from backend.cards.store import get_card_store
from backend.cards.ledger import get_decision_ledger
from backend.models.schemas import User

router = APIRouter(prefix="/api/cabinets", tags=["cabinets"])


@router.get("/{principal}/activity")
async def get_cabinet_activity(
    principal: str,
    limit: int = 20,
    offset: int = 0,
    current_user: User = None,
) -> Dict[str, Any]:
    """Get activity feed for a cabinet member.

    Args:
        principal: Cabinet member ID (queue-guardian, decision-deputy, etc.)
        limit: Number of cards to return
        offset: Pagination offset

    Returns:
        List of Memory Cards authored by this cabinet member
    """
    card_store = get_card_store()
    cards = card_store.query_by_principal(principal)

    # Paginate
    total = len(cards)
    cards = cards[offset : offset + limit]

    return {
        "principal": principal,
        "total": total,
        "limit": limit,
        "offset": offset,
        "activity": cards,
    }


@router.get("/{principal}/current-items")
async def get_cabinet_current_items(
    principal: str,
    current_user: User = None,
) -> Dict[str, Any]:
    """Get current escalations/items awaiting decision for cabinet member.

    Returns:
        List of active escalation/decision items
    """
    card_store = get_card_store()

    # Query for DecisionPackets authored by this principal that are still pending
    # (would need a "status" field in DecisionPacket to properly filter)
    cards = card_store.query_by_principal(principal)
    decision_cards = [c for c in cards if c.get("card_type") == "decision"]

    return {
        "principal": principal,
        "current_count": len(decision_cards),
        "items": decision_cards[:10],  # Limit to 10 most recent
    }


@router.post("/{principal}/items/{item_id}/approve")
async def approve_cabinet_decision(
    principal: str,
    item_id: str,
    signature: str = None,
    notes: str = None,
    current_user: User = None,
) -> Dict[str, Any]:
    """Treasurer approves a cabinet decision/draft.

    Args:
        principal: Cabinet member ID
        item_id: Decision/escalation item ID
        signature: Treasurer digital signature/approval
        notes: Optional approval notes

    Returns:
        Updated decision with approval recorded
    """
    if not current_user or current_user.role not in ["TREASURER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Only treasurers can approve")

    card_store = get_card_store()
    ledger = get_decision_ledger("default-church")  # Would get from current_user

    # Read the decision card
    card = card_store.read(item_id)
    if not card:
        raise HTTPException(status_code=404, detail="Decision not found")

    # Write approval to Decision Ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    entry = LedgerEntry(
        entry_id=f"approval-{item_id}",
        decision_id=item_id,
        category=DecisionCategory.APPROVE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": "TREASURER_ADMIN",
        },
        outcome=DecisionOutcome.ACCEPTED,
        metadata={
            "signature": signature,
            "approved_by": current_user.user_id,
            "approval_notes": notes,
        },
    )
    ledger.append(entry)

    return {
        "item_id": item_id,
        "status": "approved",
        "approved_at": datetime.utcnow().isoformat(),
        "approved_by": current_user.user_id,
    }


@router.post("/{principal}/items/{item_id}/reject")
async def reject_cabinet_decision(
    principal: str,
    item_id: str,
    reason: str,
    current_user: User = None,
) -> Dict[str, Any]:
    """Treasurer rejects a cabinet decision, sends back for revision.

    Args:
        principal: Cabinet member ID
        item_id: Decision/escalation item ID
        reason: Reason for rejection

    Returns:
        Updated decision with rejection recorded
    """
    if not current_user or current_user.role not in ["TREASURER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Only treasurers can reject")

    ledger = get_decision_ledger("default-church")

    # Write rejection to Decision Ledger
    from backend.decision_ledger import LedgerEntry, DecisionCategory, DecisionOutcome

    entry = LedgerEntry(
        entry_id=f"rejection-{item_id}",
        decision_id=item_id,
        category=DecisionCategory.ROUTE,
        timestamp=datetime.utcnow(),
        authoring_actor={
            "actor_id": current_user.user_id,
            "actor_type": "TREASURER_ADMIN",
        },
        outcome=DecisionOutcome.REJECTED,
        metadata={
            "rejected_by": current_user.user_id,
            "rejection_reason": reason,
            "send_back_to": principal,
        },
    )
    ledger.append(entry)

    return {
        "item_id": item_id,
        "status": "rejected",
        "rejected_at": datetime.utcnow().isoformat(),
        "rejected_by": current_user.user_id,
        "reason": reason,
    }
