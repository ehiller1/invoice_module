"""Exception card store — CardStore-based replacement for legacy SQL exception_cards + JSONL file store."""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


class ExceptionCardStore:
    """Exception records as MemoryCards in CardStore — single source of truth."""

    PRINCIPAL = "compliance-engine"

    @staticmethod
    async def create(
        church_id: str,
        exception_type: str,
        title: str,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
        suggested_action: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
        assigned_to: Optional[str] = None,
        principal: str = "compliance-engine",
    ) -> tuple[str, Optional[Dict[str, Any]]]:
        """Create an exception card.

        Checks if exception should be routed based on delegations.

        Args:
            church_id: Church identifier
            exception_type: Type of exception (RECONCILIATION, AMBIGUOUS_VENDOR, etc.)
            title: Short title
            description: Detailed description
            evidence: Supporting evidence dict
            suggested_action: Suggested action dict
            job_id: Optional processing job ID
            assigned_to: Optional user to assign to
            principal: Principal creating exception (for routing checks)

        Returns:
            Tuple of (card_id, routing_info) where routing_info is dict if routed, else None
        """
        from backend.membrane.routing import RoutingEngine

        card_store = get_card_store()

        card_id = f"exception-{church_id}-{datetime.utcnow().timestamp()}"
        validate_id_component(card_id, field="card_id")

        metadata = {
            "church_id": church_id,
            "exception_type": exception_type,
            "title": title,
            "description": description,
            "evidence": evidence or {},
            "suggested_action": suggested_action or {},
            "job_id": job_id,
            "assigned_to": assigned_to,
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
            "resolution": None,
        }

        card = MemoryCard(
            card_id=card_id,
            principal=ExceptionCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"{exception_type}: {title}",
            confidence=0.85,
            metadata=metadata,
        )

        card_store.write(card, chain=True)
        logger.info("Created exception card %s for %s", card_id, exception_type)

        routing = await RoutingEngine.route_decision(
            principal=principal,
            church_id=church_id,
            decision_type="exception",
            decision_id=card_id,
            decision_context={
                "exception_type": exception_type,
                "has_suggested_action": bool(suggested_action),
            },
            decision_subject=title,
        )

        if routing:
            metadata["routed_to"] = routing.get("target")
            metadata["routing_rule"] = routing.get("rule_id")
            logger.info(
                "Exception %s routed to %s via rule %s",
                card_id,
                routing.get("target"),
                routing.get("rule_id"),
            )

        return card_id, routing

    @staticmethod
    async def list_by_status(
        church_id: str,
        status: str = "open",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List exception cards by status.

        Args:
            church_id: Church identifier
            status: Filter by status (open, resolved)
            limit: Number of results
            offset: Pagination offset

        Returns:
            Tuple of (cards, total_count)
        """
        card_store = get_card_store()

        all_cards = card_store.query_by_principal(ExceptionCardStore.PRINCIPAL)
        filtered = [
            c
            for c in all_cards
            if c.get("metadata", {}).get("church_id") == church_id
            and c.get("metadata", {}).get("status") == status
        ]

        total = len(filtered)
        cards = filtered[offset : offset + limit]

        return (
            [
                {
                    "card_id": c.get("card_id"),
                    "exception_type": c.get("metadata", {}).get("exception_type"),
                    "title": c.get("metadata", {}).get("title"),
                    "description": c.get("metadata", {}).get("description"),
                    "status": c.get("metadata", {}).get("status"),
                    "assigned_to": c.get("metadata", {}).get("assigned_to"),
                    "created_at": c.get("created_at"),
                }
                for c in cards
            ],
            total,
        )

    @staticmethod
    async def resolve(
        card_id: str,
        resolution: str,
    ) -> None:
        """Resolve an exception card.

        Args:
            card_id: Card ID to resolve
            resolution: Resolution description
        """
        card_store = get_card_store()

        card = card_store.read(card_id)
        if not card:
            logger.warning("Card %s not found for resolution", card_id)
            return

        metadata = card.get("metadata", {})
        metadata["status"] = "resolved"
        metadata["resolved_at"] = datetime.utcnow().isoformat()
        metadata["resolution"] = resolution

        resolved_card = MemoryCard(
            card_id=f"{card_id}-resolved",
            principal=ExceptionCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Resolved: {resolution}",
            confidence=0.95,
            metadata=metadata,
        )

        card_store.write(resolved_card, chain=True)
        logger.info("Resolved exception card %s", card_id)
