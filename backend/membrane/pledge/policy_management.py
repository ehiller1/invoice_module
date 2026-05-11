"""Phase 17: Policy Management — Financial Policy Governance.

Define, vote on, and enforce financial policies.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)

POLICY_PRINCIPAL = "policy-engine"


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
        Policy data dict
    """
    validate_id_component(policy_id, field="policy_id")
    card_store = get_card_store()

    policy_data = {
        "policy_id": policy_id,
        "title": title,
        "description": description,
        "rules": policy_rules,
        "effective_date": effective_date,
        "enforcement_level": enforcement_level,
        "status": "draft",
        "votes_required": 3,
        "votes": {},
        "created_at": datetime.utcnow().isoformat(),
    }

    policy_card = MemoryCard(
        card_id=f"policy-{policy_id}",
        principal=POLICY_PRINCIPAL,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=json.dumps(policy_data),
        confidence=0.95,
        metadata={
            "policy_id": policy_id,
            "title": title,
            "description": description,
            "rules": policy_rules,
            "effective_date": effective_date,
            "enforcement_level": enforcement_level,
            "status": "draft",
            "votes_required": 3,
            "votes": {},
        },
    )

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

    card = card_store.read(f"policy-{policy_id}")
    if not card:
        return None

    metadata = card.get("metadata", {})
    return {
        "policy_id": policy_id,
        "title": metadata.get("title"),
        "description": metadata.get("description"),
        "rules": metadata.get("rules", {}),
        "effective_date": metadata.get("effective_date"),
        "enforcement_level": metadata.get("enforcement_level", "warning"),
        "status": metadata.get("status", "draft"),
        "votes_required": metadata.get("votes_required", 3),
        "votes": metadata.get("votes", {}),
        "created_at": card.get("created_at"),
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

    all_cards = card_store.query_by_principal(POLICY_PRINCIPAL)
    policy_cards = [c for c in all_cards if str(c.get("card_id", "")).startswith("policy-")]

    if status:
        policy_cards = [p for p in policy_cards if p.get("metadata", {}).get("status") == status]

    total = len(policy_cards)
    page = policy_cards[offset: offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "policies": [
            {
                "policy_id": c.get("metadata", {}).get("policy_id", c.get("card_id", "").replace("policy-", "")),
                "title": c.get("metadata", {}).get("title"),
                "description": c.get("metadata", {}).get("description"),
                "status": c.get("metadata", {}).get("status", "draft"),
                "enforcement_level": c.get("metadata", {}).get("enforcement_level", "warning"),
                "effective_date": c.get("metadata", {}).get("effective_date"),
                "created_at": c.get("created_at"),
            }
            for c in page
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
    validate_id_component(policy_id, field="policy_id")
    validate_id_component(voter_id, field="voter_id")
    card_store = get_card_store()

    vote_data = {
        "policy_id": policy_id,
        "voter_id": voter_id,
        "vote": vote,
        "rationale": rationale,
        "timestamp": datetime.utcnow().isoformat(),
    }

    vote_card = MemoryCard(
        card_id=f"vote-{policy_id}-{voter_id}",
        principal=POLICY_PRINCIPAL,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Vote on policy {policy_id}: {vote}" + (f" - {rationale}" if rationale else ""),
        confidence=1.0,
        metadata=vote_data,
    )

    card_store.write(vote_card, chain=True)

    return vote_data


async def check_policy_compliance(
    transaction_amount: float,
    account: str,
    department: str,
    transaction_type: str,
) -> Dict[str, Any]:
    """Check if a transaction violates any active policies.

    Queries policy-engine cards and evaluates each stored rule set.

    Args:
        transaction_amount: Amount of transaction
        account: GL account
        department: Department code
        transaction_type: Type of transaction (purchase, travel, etc.)

    Returns:
        Compliance check result with violations list
    """
    card_store = get_card_store()

    all_cards = card_store.query_by_principal(POLICY_PRINCIPAL)
    policy_cards = [c for c in all_cards if str(c.get("card_id", "")).startswith("policy-")]

    violations = []

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
    """Get policy status from card metadata."""
    return policy_card.get("metadata", {}).get("status", "active")


def _check_policy_rule(
    policy_card: Dict[str, Any],
    amount: float,
    account: str,
    department: str,
    transaction_type: str,
) -> Optional[Dict[str, Any]]:
    """Check if transaction violates a stored policy rule.

    Reads actual rule definitions from card metadata.
    """
    metadata = policy_card.get("metadata", {})
    rules = metadata.get("rules", {})
    enforcement = metadata.get("enforcement_level", "warning")

    # Skip archived/draft policies
    if metadata.get("status") in ("archived", "draft"):
        return None

    # Check amount limit
    amount_limit = rules.get("amount_limit")
    if amount_limit is not None and amount > amount_limit:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "amount_limit",
            "message": f"Transaction amount ${amount} exceeds policy limit of ${amount_limit}",
            "severity": enforcement,
        }

    # Check department-specific limits
    dept_limits = rules.get("department_limits", {})
    if department in dept_limits and amount > dept_limits[department]:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "department_limit",
            "message": f"Department '{department}' limit of ${dept_limits[department]} exceeded by ${amount}",
            "severity": enforcement,
        }

    # Check restricted accounts
    restricted_accounts = rules.get("restricted_accounts", [])
    if account in restricted_accounts:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "restricted_account",
            "message": f"Account {account} is restricted by this policy",
            "severity": enforcement,
        }

    # Check restricted transaction types
    restricted_types = rules.get("restricted_transaction_types", [])
    if transaction_type in restricted_types:
        return {
            "policy_id": policy_card.get("card_id"),
            "violation_type": "restricted_transaction_type",
            "message": f"Transaction type '{transaction_type}' is not permitted",
            "severity": enforcement,
        }

    return None
