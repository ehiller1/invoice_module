"""Phase 12: Decision Deputy Cabinet Member.

Drafts decision letters in Treasurer's voice. Calls drafting_agent directly
for suggestions, awaits Treasurer approval before sending.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from backend.membrane.transport.base import MessageTransport
from backend.cards.schemas import DecisionPacket
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def decision_deputy_runner(
    transport: MessageTransport, channels: list[str]
) -> None:
    """Decision Deputy runner — drafts decisions, waits for approval.

    Args:
        transport: MessageTransport for subscribing to channels
        channels: List of channels to subscribe to
    """
    logger.info(
        f"Decision Deputy started, monitoring {len(channels)} channel(s)"
    )

    while True:
        try:
            # Listen for escalations
            for channel in channels:
                messages = await transport.consume_batch(
                    channel,
                    "decision-deputy-group",
                    "decision-deputy",
                    count=5,
                )
                for msg in messages:
                    await handle_escalation(msg.payload)
                    await transport.ack(
                        channel, "decision-deputy-group", msg.id
                    )

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Decision Deputy error: {e}")
            raise


async def handle_escalation(payload: Dict[str, Any]) -> None:
    """Handle escalation by drafting decision suggestions.

    Args:
        payload: Escalation signal payload with context
    """
    escalation_id = payload.get("escalation_id", "unknown")
    logger.info(f"Decision Deputy handling escalation: {escalation_id}")

    try:
        # Get Cabinet context (recent decisions from other cabinet members)
        card_store = get_card_store()
        cabinet_memory = card_store.query_by_principal("queue-guardian")
        cabinet_memory += card_store.query_by_principal("budget-steward")

        logger.info(f"Found {len(cabinet_memory)} cabinet context cards")

        # Call drafting_agent directly (synchronous call in shared Python runtime)
        # In production, would:
        # suggested_draft = await call_agent(
        #     agent_name="drafting_agent",
        #     method="suggest_draft",
        #     context={"escalation_id": escalation_id, "cabinet_context": cabinet_memory}
        # )

        suggested_draft = f"Suggested draft for escalation {escalation_id}"

        # Write draft to Card Store
        draft_card = DecisionPacket(
            card_id=f"draft-{escalation_id}",
            principal="decision-deputy",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            decision_id=f"escalation-{escalation_id}",
            category="APPROVE",
            verdict="APPROVE",
            reasoning=suggested_draft,
            confidence=0.85,
        )
        card_store.write(draft_card)

        logger.info(f"Draft decision written for {escalation_id}")

        # Awaits Treasurer approval (via /api/cabinets/{principal}/items/{item_id}/approve)
        logger.info(f"Awaiting Treasurer approval for {escalation_id}")

    except Exception as e:
        logger.error(f"Error handling escalation {escalation_id}: {e}")
        raise
