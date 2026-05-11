"""Delegation store — CardStore-based persistence for decision routing rules."""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from backend.cards.ids import validate_id_component
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


class DelegationCardStore:
    """Delegation rules as MemoryCards in CardStore — immutable audit trail."""

    PRINCIPAL = "governance-engine"

    @staticmethod
    async def create(
        principal: str,
        church_id: str,
        delegation_type: str,
        decision_type: str,
        target: str,
        trigger_condition: Optional[str] = None,
        notification_level: str = "escalation_only",
    ) -> str:
        """Create a delegation rule.

        Args:
            principal: Cabinet member ID (treasurer, cfo, etc.)
            church_id: Church identifier
            delegation_type: agent|member|threshold
            decision_type: exception|pledge|policy|variance|fund_restriction
            target: Agent ID or cabinet member name
            trigger_condition: Optional condition (e.g., "variance_pct > 5%")
            notification_level: always|escalation_only|never

        Returns:
            Card ID (delegation-{uuid})
        """
        validate_id_component(principal, field="principal")
        validate_id_component(church_id, field="church_id")

        card_store = get_card_store()

        card_id = f"delegation-{principal}-{decision_type}-{datetime.utcnow().timestamp()}"

        metadata = {
            "principal": principal,
            "church_id": church_id,
            "delegation_type": delegation_type,
            "decision_type": decision_type,
            "target": target,
            "trigger_condition": trigger_condition,
            "notification_level": notification_level,
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "created_by": principal,
            "is_governance_decision": True,
            "governance_type": "delegation_rule",
        }

        card = MemoryCard(
            card_id=card_id,
            principal=DelegationCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Delegation: {decision_type} → {target} (condition: {trigger_condition or 'always'})",
            confidence=1.0,
            metadata=metadata,
        )

        card_store.write(card, chain=True)
        logger.info(
            "Created delegation: %s routes %s to %s [%s]",
            principal,
            decision_type,
            target,
            card_id,
        )

        return card_id

    @staticmethod
    async def get_delegations_for_principal(
        principal: str,
        church_id: str,
        decision_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get active delegations for a principal.

        Args:
            principal: Cabinet member ID
            church_id: Church identifier
            decision_type: Optional filter by decision type

        Returns:
            List of active delegation rules
        """
        card_store = get_card_store()

        all_cards = card_store.query_by_principal(DelegationCardStore.PRINCIPAL)
        delegations = [
            c
            for c in all_cards
            if str(c.get("card_id", "")).startswith("delegation-")
            and c.get("metadata", {}).get("principal") == principal
            and c.get("metadata", {}).get("church_id") == church_id
            and c.get("metadata", {}).get("status") == "active"
        ]

        if decision_type:
            delegations = [
                d
                for d in delegations
                if d.get("metadata", {}).get("decision_type") == decision_type
            ]

        return [
            {
                "card_id": c.get("card_id"),
                "delegation_type": c.get("metadata", {}).get("delegation_type"),
                "decision_type": c.get("metadata", {}).get("decision_type"),
                "target": c.get("metadata", {}).get("target"),
                "trigger_condition": c.get("metadata", {}).get("trigger_condition"),
                "notification_level": c.get("metadata", {}).get("notification_level"),
                "created_at": c.get("metadata", {}).get("created_at"),
            }
            for c in delegations
        ]

    @staticmethod
    async def evaluate_routing(
        principal: str,
        church_id: str,
        decision_type: str,
        decision_context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Evaluate if a decision should be routed based on delegation rules.

        Args:
            principal: Cabinet member ID
            church_id: Church identifier
            decision_type: Type of decision (exception, pledge, etc.)
            decision_context: Context dict with decision attributes (amount, variance_pct, etc.)

        Returns:
            {target, delegation_type, notify} if delegation applies, None otherwise
        """
        delegations = await DelegationCardStore.get_delegations_for_principal(
            principal, church_id, decision_type
        )

        for deleg in delegations:
            trigger_condition = deleg.get("trigger_condition")

            if not trigger_condition:
                return {
                    "target": deleg.get("target"),
                    "delegation_type": deleg.get("delegation_type"),
                    "notification_level": deleg.get("notification_level"),
                    "rule_id": deleg.get("card_id"),
                }

            if _evaluate_condition(trigger_condition, decision_context):
                return {
                    "target": deleg.get("target"),
                    "delegation_type": deleg.get("delegation_type"),
                    "notification_level": deleg.get("notification_level"),
                    "rule_id": deleg.get("card_id"),
                }

        return None

    @staticmethod
    async def revoke_delegation(
        card_id: str,
        revoked_by: str,
        reason: str,
    ) -> str:
        """Revoke an active delegation.

        Args:
            card_id: Delegation card ID
            revoked_by: Principal revoking
            reason: Revocation reason

        Returns:
            Revocation card ID
        """
        card_store = get_card_store()

        revocation_card_id = f"{card_id}-revoked"

        revocation_card = MemoryCard(
            card_id=revocation_card_id,
            principal=DelegationCardStore.PRINCIPAL,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Revoked delegation {card_id}: {reason}",
            confidence=1.0,
            metadata={
                "original_card_id": card_id,
                "revoked_by": revoked_by,
                "reason": reason,
                "revoked_at": datetime.utcnow().isoformat(),
                "status": "revoked",
            },
        )

        card_store.write(revocation_card, chain=True)
        logger.info(
            "Revoked delegation %s by %s: %s",
            card_id,
            revoked_by,
            reason,
        )

        return revocation_card_id


def _evaluate_condition(condition_str: str, context: Dict[str, Any]) -> bool:
    """Evaluate a trigger condition against decision context.

    Simple expression evaluator supporting:
    - Comparison: variance_pct > 5, amount > 1000
    - Operators: >, <, >=, <=, ==, !=
    - Logical: and, or

    Args:
        condition_str: Condition expression
        context: Decision context dict

    Returns:
        True if condition matches, False otherwise
    """
    try:
        for key, value in context.items():
            condition_str = condition_str.replace(key, str(value))

        result = eval(condition_str, {"__builtins__": {}}, {})
        return bool(result)
    except Exception as e:
        logger.warning("Failed to evaluate condition '%s': %s", condition_str, e)
        return False
