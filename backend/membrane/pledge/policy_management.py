"""Phase 17: Policy Management — Financial Policy Governance.

Define, vote on, and enforce financial policies.
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional

from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def create_policy(
    policy_id: str,
    title: str,
    description: str,
    policy_rules: Dict[str, Any],
    effective_date: str,
    enforcement_level: str = "warning",  # warning, blocking
) -> Dict[str, Any]:
    """Create a new financial policy.

    Args:
        policy_id: Unique policy identifier
        title: Policy title
        description: Policy description
        policy_rules: Policy rule definitions
        effective_date: Date policy becomes effective
        enforcement_level: warning (flag) or blocking (prevent)

    Returns:
        Policy card
    """
    card_store = get_card_store()

    policy_card = MemoryCard(
        card_id=f"policy-{policy_id}",
        principal="policy-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Policy: {title}. {description}",
        confidence=0.95,
    )

    policy_data = {
        "policy_id": policy_id,
        "title": title,
        "description": description,
        "rules": policy_rules,
        "effective_date": effective_date,
        "enforcement_level": enforcement_level,
        "status": "draft",
        "votes_required": 3,  # Quorum for approval
        "votes": {},
        "created_at": datetime.utcnow().isoformat(),
    }

    card_store.write(policy_card, chain=True)

    return policy_data


async def get_policy(policy_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a policy by ID.

    Args:
        policy_id: Policy identifier

    Returns:
        Policy details or None
    """
    card_store = get_card_store()

    all_cards = card_store.query_by_principal("decision-deputy")
    policy_cards = [
        c for c in all_cards
        if f"policy-{policy_id}" in str(c.get("card_id", ""))
    ]

    if not policy_cards:
        return None

    return {
        "policy_id": policy_id,
        "content": policy_cards[0].get("content"),
        "created_at": policy_cards[0].get("created_at"),
        "status": "active",
    }


async def list_policies(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List policies with optional filtering.

    Args:
        status: Optional status filter (draft, active, archived)
        limit: Number of results
        offset: Pagination offset

    Returns:
        List of policies
    """
    card_store = get_card_store()

    all_cards = card_store.query_by_principal("decision-deputy")
    policy_cards = [
        c for c in all_cards
        if "policy-" in str(c.get("card_id", ""))
    ]

    if status:
        policy_cards = [p for p in policy_cards if _get_policy_status(p) == status]

    total = len(policy_cards)
    policies = policy_cards[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "policies": [
            {
                "policy_id": c.get("card_id", "").replace("policy-", ""),
                "content": c.get("content"),
                "created_at": c.get("created_at"),
            }
            for c in policies
        ],
    }


async def vote_on_policy(
    policy_id: str,
    voter_id: str,
    vote: str,  # approve, reject, abstain
    rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a vote on a policy.

    Args:
        policy_id: Policy identifier
        voter_id: ID of voter
        vote: approve, reject, or abstain
        rationale: Optional voting rationale

    Returns:
        Vote record
    """
    card_store = get_card_store()

    # Create vote record
    vote_card = MemoryCard(
        card_id=f"vote-{policy_id}-{voter_id}",
        principal="policy-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Vote on policy {policy_id}: {vote}" +
                (f" - {rationale}" if rationale else ""),
        confidence=1.0,
    )

    vote_data = {
        "policy_id": policy_id,
        "voter_id": voter_id,
        "vote": vote,
        "rationale": rationale,
        "timestamp": datetime.utcnow().isoformat(),
    }

    card_store.write(vote_card, chain=True)

    return vote_data


async def check_policy_compliance(
    transaction_amount: float,
    account: str,
    department: str,
    transaction_type: str,
) -> Dict[str, Any]:
    """Check if a transaction violates any policies.

    Args:
        transaction_amount: Amount of transaction
        account: GL account
        department: Department code
        transaction_type: Type of transaction (purchase, travel, etc.)

    Returns:
        Compliance check result
    """
    card_store = get_card_store()

    # Query active policies
    all_cards = card_store.query_by_principal("decision-deputy")
    policy_cards = [
        c for c in all_cards
        if "policy-" in str(c.get("card_id", ""))
    ]

    violations = []

    # Check each policy
    for policy in policy_cards:
        violation = _check_policy_rule(
            policy,
            transaction_amount,
            account,
            department,
            transaction_type,
        )
        if violation:
            violations.append(violation)

    return {
        "compliant": len(violations) == 0,
        "violations": violations,
        "violation_count": len(violations),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ===== Helper Functions =====


def _get_policy_status(policy_card: Dict[str, Any]) -> str:
    """Get policy status from card."""
    content = policy_card.get("content", "").lower()
    if "archived" in content:
        return "archived"
    if "draft" in content:
        return "draft"
    return "active"


def _check_policy_rule(
    policy_card: Dict[str, Any],
    amount: float,
    account: str,
    department: str,
    transaction_type: str,
) -> Optional[Dict[str, Any]]:
    """Check if transaction violates a policy rule."""
    # Placeholder: would parse policy rules and check compliance

    # Placeholder: would parse policy rules and check compliance
    # For now, return None (no violation) unless amount exceeds threshold

    if amount > 10000:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "amount_threshold",
            "message": f"Transaction amount ${amount} exceeds policy threshold",
            "severity": "warning",
        }

    # Check for restricted departments
    if department in ["travel", "entertainment"] and amount > 5000:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "department_limit",
            "message": f"Department {department} transaction exceeds limit",
            "severity": "warning",
        }

    return None
