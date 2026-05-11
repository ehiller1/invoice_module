"""Phase 12: Queue Guardian Cabinet Member.

Sentinels on approval deadline pressure, HITL escalation, budget overage risk.
Wakes daily at 8 AM to send digest of queue status.
"""

import asyncio
import logging
from datetime import datetime, time

from backend.membrane.transport.base import MessageTransport
from backend.membrane.reconciliation.dedup_integration import (
    get_payment_dedup_integration,
)
from backend.membrane.reconciliation.recon_integration import (
    get_reconciliation_integration,
)
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def queue_guardian_runner(
    transport: MessageTransport, channels: list[str]
) -> None:
    """Queue Guardian runner — monitors approval queue and sends daily digests.

    Args:
        transport: MessageTransport for subscribing to channels
        channels: List of channels to subscribe to
    """
    logger.info(f"Queue Guardian started, monitoring {len(channels)} channel(s)")

    # For now, just listen for signals
    # In production, would:
    # 1. Subscribe to channels via transport
    # 2. On signal arrival, analyze queue
    # 3. Send digest email
    # 4. Emit context via Card Store

    while True:
        try:
            # Check for upcoming deadline pressure (8 AM daily)
            now = datetime.utcnow()
            if now.time() >= time(8, 0) and now.time() < time(8, 5):
                await send_daily_digest()

            # Listen for signals on subscribed channels
            for channel in channels:
                messages = await transport.consume_batch(
                    channel, "queue-guardian-group", "queue-guardian", count=10
                )
                for msg in messages:
                    await handle_signal(msg.payload)
                    await transport.ack(channel, "queue-guardian-group", msg.id)

            await asyncio.sleep(30)  # Poll every 30s

        except Exception as e:
            logger.error(f"Queue Guardian error: {e}")
            raise


async def send_daily_digest() -> None:
    """Send daily digest of queue status."""
    logger.info("Sending daily queue digest")

    # Query current queue status
    dedup_integration = get_payment_dedup_integration()
    recon_integration = get_reconciliation_integration()

    # Placeholder: would build digest from actual queue data
    digest_content = {
        "timestamp": datetime.utcnow().isoformat(),
        "escalations": 0,  # Would query from queue
        "budget_warnings": 0,  # Would query from budget system
        "unmatched_transactions": 0,  # Would query from recon
    }

    # Write to Card Store
    from backend.cards.schemas import MemoryCard
    from backend.cards.store import get_card_store

    card_store = get_card_store()
    card = MemoryCard(
        card_id=f"qg-digest-{datetime.utcnow().isoformat()}",
        principal="queue-guardian",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Daily digest: {digest_content}",
        confidence=0.95,
    )
    card_store.write(card)

    logger.info("Daily digest sent and recorded")


async def handle_signal(payload: dict) -> None:
    """Handle incoming signal (escalation, deadline pressure, etc.)."""
    signal_type = payload.get("signal_type")
    logger.info(f"Queue Guardian received signal: {signal_type}")

    if signal_type == "approval_deadline_pressure":
        logger.info(f"Deadline pressure: {payload}")
    elif signal_type == "hitl_escalation":
        logger.info(f"HITL escalation: {payload}")
    elif signal_type == "budget_overage_risk":
        logger.info(f"Budget overage risk: {payload}")
