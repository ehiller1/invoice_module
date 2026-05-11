"""Phase 12: Budget Steward Cabinet Member.

Monitors budget overage risk, sends weekly budget digests Friday 4 PM.
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Any, Dict

from backend.membrane.transport.base import MessageTransport
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def budget_steward_runner(
    transport: MessageTransport, channels: list[str]
) -> None:
    """Budget Steward runner — monitors budget, sends weekly digest Friday 4 PM.

    Args:
        transport: MessageTransport for subscribing to channels
        channels: List of channels to subscribe to
    """
    logger.info(
        f"Budget Steward started, monitoring {len(channels)} channel(s)"
    )

    while True:
        try:
            # Check for Friday 4 PM digest time
            now = datetime.utcnow()
            if (
                now.weekday() == 4  # Friday (0=Monday, 4=Friday)
                and now.time() >= time(16, 0)
                and now.time() < time(16, 5)
            ):
                await send_weekly_budget_digest()

            # Listen for budget overage signals
            for channel in channels:
                messages = await transport.consume_batch(
                    channel,
                    "budget-steward-group",
                    "budget-steward",
                    count=5,
                )
                for msg in messages:
                    await handle_budget_signal(msg.payload)
                    await transport.ack(
                        channel, "budget-steward-group", msg.id
                    )

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Budget Steward error: {e}")
            raise


async def send_weekly_budget_digest() -> None:
    """Send weekly budget digest (Friday 4 PM)."""
    logger.info("Sending weekly budget digest")

    # Query budget status
    # In production would query actual budget system
    digest_data = {
        "week_ending": datetime.utcnow().isoformat(),
        "total_budget": 100000.00,
        "spent_ytd": 45000.00,
        "variance_percent": 45.0,
        "at_risk_accounts": [],
    }

    # Write to Card Store
    card_store = get_card_store()
    card = MemoryCard(
        card_id=f"bs-digest-{datetime.utcnow().isoformat()}",
        principal="budget-steward",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        content=f"Weekly budget digest: {digest_data}",
        confidence=0.90,
    )
    card_store.write(card)

    logger.info("Weekly budget digest sent and recorded")


async def handle_budget_signal(payload: Dict[str, Any]) -> None:
    """Handle budget overage or variance signals.

    Args:
        payload: Signal payload with budget details
    """
    signal_type = payload.get("signal_type")
    logger.info(f"Budget Steward received signal: {signal_type}")

    if signal_type == "budget_overage_risk":
        account = payload.get("account")
        variance = payload.get("variance_percent", 0)
        logger.info(
            f"Budget overage risk on account {account}: {variance}% variance"
        )

        # Write warning card
        card_store = get_card_store()
        card = MemoryCard(
            card_id=f"budget-warning-{account}-{datetime.utcnow().isoformat()}",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Budget warning: Account {account} at {variance}% variance",
            confidence=0.95,
        )
        card_store.write(card)
    elif signal_type == "journal_entry_ready":
        logger.info(f"Journal entry ready for post: {payload}")
