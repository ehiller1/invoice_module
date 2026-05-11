"""Policy card store — CardStore-based replacement for legacy SQL policy_cards."""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


class PolicyCardStore:
    """Policy cards as MemoryCards in CardStore — single source of truth."""

    PRINCIPAL = "policy-engine"

    @staticmethod
    async def create(
        church_id: str,
        policy_id: str,
        title: str,
        description: str,
        policy_rules: Dict[str, Any],
        effective_date: str,
        enforcement_level: str = "warning",
        proposed_by: Optional[str] = None,
    ) -> str:
        """Create a policy card.

        Args:
            church_id: Church identifier
            policy_id: Unique policy ID
            title: Policy title
            description: Policy description
            policy_rules: Rule definitions dict
            effective_date: Effective date (ISO format)
            enforcement_level: warning or blocking
            proposed_by: Optional proposer ID

        Returns:
            Card ID
        """
        validate_id_component(policy_id, field="policy_id")
        card_store = get_card_store()

        card_id = f"policy-{policy_id}"

        metadata = {
            "church_id": church_id,
            "policy_id": policy_id,
            "title": title,
            "description": description,
            "rules": policy_rules,
            "effective_date": effective_date,
            "enforcement_level": enforcement_level,
            "proposed_by": proposed_by,
            "status": "draft",
            "votes_required": 3,
            "votes": {},
            "created_at": datetime.utcnow().isoformat(),
        }

        card = MemoryCard(
            card_id=card_id,
            principal=PolicyCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=json.dumps(metadata),
            confidence=0.95,
            metadata=metadata,
        )

        card_store.write(card, chain=True)
        logger.info("Created policy card %s (%s)", card_id, policy_id)

        return card_id

    @staticmethod
    async def get(policy_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a policy by ID.

        Args:
            policy_id: Policy identifier

        Returns:
            Policy dict or None
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

    @staticmethod
    async def list_by_status(
        church_id: str,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List policies by status.

        Args:
            church_id: Church identifier
            status: Optional status filter (draft, active, archived)
            limit: Number of results
            offset: Pagination offset

        Returns:
            Tuple of (policies, total_count)
        """
        card_store = get_card_store()

        all_cards = await card_store.aquery_by_principal(PolicyCardStore.PRINCIPAL)
        filtered = [
            c
            for c in all_cards
            if str(c.get("card_id", "")).startswith("policy-")
            and c.get("metadata", {}).get("church_id") == church_id
        ]

        if status:
            filtered = [
                p for p in filtered if p.get("metadata", {}).get("status") == status
            ]

        total = len(filtered)
        page = filtered[offset : offset + limit]

        return (
            [
                {
                    "policy_id": c.get("metadata", {}).get("policy_id"),
                    "title": c.get("metadata", {}).get("title"),
                    "description": c.get("metadata", {}).get("description"),
                    "status": c.get("metadata", {}).get("status", "draft"),
                    "enforcement_level": c.get("metadata", {}).get(
                        "enforcement_level", "warning"
                    ),
                    "effective_date": c.get("metadata", {}).get("effective_date"),
                    "created_at": c.get("created_at"),
                }
                for c in page
            ],
            total,
        )

    @staticmethod
    async def record_vote(
        policy_id: str,
        voter_id: str,
        vote: str,
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
            principal=PolicyCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Vote on policy {policy_id}: {vote}"
            + (f" - {rationale}" if rationale else ""),
            confidence=1.0,
            metadata=vote_data,
        )

        card_store.write(vote_card, chain=True)

        return vote_data
