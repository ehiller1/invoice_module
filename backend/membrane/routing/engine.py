"""Decision routing engine — evaluates delegations and routes decisions to targets."""

import logging
from typing import Dict, Any, Optional

from backend.membrane.stores.delegations import DelegationCardStore
from backend.membrane.stores.audits import AuditCardStore

logger = logging.getLogger(__name__)


class RoutingEngine:
    """Routes decisions to agents/members based on delegation rules."""

    @staticmethod
    async def route_decision(
        principal: str,
        church_id: str,
        decision_type: str,
        decision_id: str,
        decision_context: Dict[str, Any],
        decision_subject: str,
    ) -> Optional[Dict[str, Any]]:
        """Route a decision based on active delegations.

        Evaluates all delegation rules for the principal and decision type.
        If a condition matches, routes to the target agent/member and logs audit entry.

        Args:
            principal: Cabinet member ID making the decision
            church_id: Church identifier
            decision_type: exception|pledge|policy|variance|fund_restriction
            decision_id: Unique ID of the decision
            decision_context: Context dict for condition evaluation (e.g., {amount: 5000, variance_pct: 8})
            decision_subject: Human-readable subject of decision

        Returns:
            {
                target: agent_id or member_name,
                delegation_type: agent|member|threshold,
                notification_level: always|escalation_only|never,
                rule_id: delegation card ID,
                routed_at: timestamp
            }
            or None if no delegations apply
        """
        routing = await DelegationCardStore.evaluate_routing(
            principal=principal,
            church_id=church_id,
            decision_type=decision_type,
            decision_context=decision_context,
        )

        if not routing:
            logger.debug(
                "No delegation found for %s/%s/%s",
                principal,
                decision_type,
                decision_id,
            )
            return None

        target = routing.get("target")
        notify_level = routing.get("notification_level")
        rule_id = routing.get("rule_id")

        await AuditCardStore.record_event(
            church_id=church_id,
            actor_email=principal,
            action="DECISION_ROUTED",
            resource_type="DECISION",
            resource_id=decision_id,
            details={
                "decision_type": decision_type,
                "decision_subject": decision_subject,
                "routed_to": target,
                "rule_id": rule_id,
                "context": decision_context,
                "notification_level": notify_level,
            },
        )

        logger.info(
            "Routed decision %s (%s) from %s to %s via rule %s",
            decision_id,
            decision_type,
            principal,
            target,
            rule_id,
        )

        return {
            "target": target,
            "delegation_type": routing.get("delegation_type"),
            "notification_level": notify_level,
            "rule_id": rule_id,
            "routed_at": None,  # Set by caller if needed
        }

    @staticmethod
    async def record_routed_decision(
        principal: str,
        church_id: str,
        decision_id: str,
        target: str,
        decision_type: str,
        outcome: str,
    ) -> str:
        """Record the result of a routed decision.

        Args:
            principal: Original principal
            church_id: Church ID
            decision_id: Decision ID
            target: Target that handled it
            decision_type: Decision type
            outcome: approve|reject|pending

        Returns:
            Audit entry ID
        """
        audit_id = await AuditCardStore.record_event(
            church_id=church_id,
            actor_email=target,
            action="DECISION_HANDLED",
            resource_type="ROUTED_DECISION",
            resource_id=decision_id,
            details={
                "original_principal": principal,
                "delegated_to": target,
                "decision_type": decision_type,
                "outcome": outcome,
            },
        )

        logger.info(
            "Recorded routed decision %s: %s handled by %s → %s",
            decision_id,
            decision_type,
            target,
            outcome,
        )

        return audit_id
