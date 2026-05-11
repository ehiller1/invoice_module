"""Audit card store — CardStore-based replacement for legacy SQL approval_audit_events."""

import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


class AuditCardStore:
    """Audit events as MemoryCards in CardStore — immutable chain with SHA-256 hashing."""

    PRINCIPAL = "audit-engine"

    @staticmethod
    def _compute_hash(data: Dict[str, Any], prev_hash: Optional[str] = None) -> str:
        """Compute SHA-256 hash of audit event (for chain integrity).

        Args:
            data: Event data dict
            prev_hash: Previous hash in chain

        Returns:
            SHA-256 hash hex string
        """
        combined = str(data) + (prev_hash or "")
        return hashlib.sha256(combined.encode()).hexdigest()

    @staticmethod
    async def record_event(
        church_id: str,
        actor_email: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Record an audit event in the chain.

        Args:
            church_id: Church identifier
            actor_email: Email of user performing action
            action: Action performed (CREATE, UPDATE, DELETE, APPROVE, REJECT, etc.)
            resource_type: Type of resource affected (POLICY, EXCEPTION, PLEDGE, etc.)
            resource_id: ID of resource affected
            details: Optional additional details dict

        Returns:
            Card ID of audit event
        """
        validate_id_component(church_id, field="church_id")
        card_store = get_card_store()

        event_data = {
            "church_id": church_id,
            "actor_email": actor_email,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        }

        last_event = await AuditCardStore._get_last_event(church_id)
        prev_hash = last_event.get("metadata", {}).get("hash") if last_event else None
        current_hash = AuditCardStore._compute_hash(event_data, prev_hash)

        event_data["prev_hash"] = prev_hash
        event_data["hash"] = current_hash

        card_id = f"audit-{church_id}-{datetime.utcnow().timestamp()}"

        card = MemoryCard(
            card_id=card_id,
            principal=AuditCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"{action} {resource_type} {resource_id} by {actor_email}",
            confidence=1.0,
            metadata=event_data,
        )

        card_store.write(card, chain=True)
        logger.info(
            "Recorded audit event: %s %s %s by %s",
            action,
            resource_type,
            resource_id,
            actor_email,
        )

        return card_id

    @staticmethod
    async def _get_last_event(church_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent audit event for a church (for chain integrity).

        Args:
            church_id: Church identifier

        Returns:
            Last audit event card or None
        """
        card_store = get_card_store()

        all_cards = card_store.query_by_principal(AuditCardStore.PRINCIPAL)
        events = [
            c
            for c in all_cards
            if str(c.get("card_id", "")).startswith("audit-")
            and c.get("metadata", {}).get("church_id") == church_id
        ]

        if not events:
            return None

        sorted_events = sorted(
            events,
            key=lambda e: e.get("metadata", {}).get("timestamp", ""),
            reverse=True,
        )
        return sorted_events[0] if sorted_events else None

    @staticmethod
    async def list_events(
        church_id: str,
        resource_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List audit events for a church.

        Args:
            church_id: Church identifier
            resource_type: Optional filter by resource type
            limit: Number of results
            offset: Pagination offset

        Returns:
            Tuple of (events, total_count)
        """
        card_store = get_card_store()

        all_cards = card_store.query_by_principal(AuditCardStore.PRINCIPAL)
        filtered = [
            c
            for c in all_cards
            if str(c.get("card_id", "")).startswith("audit-")
            and c.get("metadata", {}).get("church_id") == church_id
        ]

        if resource_type:
            filtered = [
                c
                for c in filtered
                if c.get("metadata", {}).get("resource_type") == resource_type
            ]

        total = len(filtered)
        sorted_events = sorted(
            filtered,
            key=lambda e: e.get("metadata", {}).get("timestamp", ""),
            reverse=True,
        )
        page = sorted_events[offset : offset + limit]

        return (
            [
                {
                    "card_id": c.get("card_id"),
                    "actor_email": c.get("metadata", {}).get("actor_email"),
                    "action": c.get("metadata", {}).get("action"),
                    "resource_type": c.get("metadata", {}).get("resource_type"),
                    "resource_id": c.get("metadata", {}).get("resource_id"),
                    "timestamp": c.get("metadata", {}).get("timestamp"),
                    "hash": c.get("metadata", {}).get("hash"),
                }
                for c in page
            ],
            total,
        )

    @staticmethod
    async def verify_chain_integrity(church_id: str) -> Dict[str, Any]:
        """Verify the audit chain for a church (no tampering).

        Args:
            church_id: Church identifier

        Returns:
            {valid: bool, broken_at: str|None, error_message: str|None}
        """
        card_store = get_card_store()

        all_cards = card_store.query_by_principal(AuditCardStore.PRINCIPAL)
        events = [
            c
            for c in all_cards
            if str(c.get("card_id", "")).startswith("audit-")
            and c.get("metadata", {}).get("church_id") == church_id
        ]

        sorted_events = sorted(
            events,
            key=lambda e: e.get("metadata", {}).get("timestamp", ""),
        )

        for i, event in enumerate(sorted_events):
            metadata = event.get("metadata", {})
            current_hash = metadata.get("hash")
            prev_hash = metadata.get("prev_hash")

            event_data = {
                k: v
                for k, v in metadata.items()
                if k not in ("hash", "prev_hash")
            }

            computed_hash = AuditCardStore._compute_hash(event_data, prev_hash)

            if computed_hash != current_hash:
                return {
                    "valid": False,
                    "broken_at": event.get("card_id"),
                    "error_message": f"Hash mismatch at event {i}: expected {computed_hash}, got {current_hash}",
                }

        return {
            "valid": True,
            "broken_at": None,
            "error_message": None,
        }
