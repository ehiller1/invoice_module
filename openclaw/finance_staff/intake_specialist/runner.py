"""Phase 12: Intake Specialist Cabinet Member.

Screener for invoice ingestion. Screens for GL suggestions, vendor flags,
anomalies. Finance staff reviews screening cards before GL mapping.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from backend.membrane.transport.base import MessageTransport
from backend.cards.schemas import MemoryCard
from backend.cards.store import get_card_store

logger = logging.getLogger(__name__)


async def intake_specialist_runner(
    transport: MessageTransport, channels: list[str]
) -> None:
    """Intake Specialist runner — screens invoices on ingestion.

    Args:
        transport: MessageTransport for subscribing to channels
        channels: List of channels to subscribe to (typically invoice_ingested)
    """
    logger.info(
        f"Intake Specialist started, monitoring {len(channels)} channel(s)"
    )

    while True:
        try:
            # Listen for invoice ingestion signals
            for channel in channels:
                messages = await transport.consume_batch(
                    channel,
                    "intake-specialist-group",
                    "intake-specialist",
                    count=10,
                )
                for msg in messages:
                    await screen_invoice(msg.payload)
                    await transport.ack(
                        channel, "intake-specialist-group", msg.id
                    )

            await asyncio.sleep(30)

        except Exception as e:
            logger.error(f"Intake Specialist error: {e}")
            raise


async def screen_invoice(payload: Dict[str, Any]) -> None:
    """Screen invoice for GL suggestions, vendor flags, anomalies.

    Args:
        payload: Invoice signal with vendor, amount, description
    """
    invoice_id = payload.get("invoice_id", "unknown")
    vendor = payload.get("vendor", "unknown")
    amount = payload.get("amount", 0)

    logger.info(f"Intake Specialist screening invoice {invoice_id} from {vendor}")

    try:
        # Analyze invoice
        analysis = await analyze_invoice(invoice_id, vendor, amount)

        # Write screening card
        card_store = get_card_store()
        card = MemoryCard(
            card_id=f"screening-{invoice_id}",
            principal="intake-specialist",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content=f"Invoice screening: {invoice_id} - {analysis}",
            confidence=analysis.get("confidence", 0.75),
        )
        card_store.write(card)

        logger.info(
            f"Screening card written for {invoice_id}. Finance staff review required."
        )

    except Exception as e:
        logger.error(f"Error screening invoice {invoice_id}: {e}")
        raise


async def analyze_invoice(
    invoice_id: str, vendor: str, amount: float
) -> Dict[str, Any]:
    """Analyze invoice for GL suggestions and flags.

    Args:
        invoice_id: Invoice identifier
        vendor: Vendor name
        amount: Invoice amount

    Returns:
        Analysis dict with suggestions and flags
    """
    # Placeholder: would call actual GL mapping service
    return {
        "invoice_id": invoice_id,
        "vendor": vendor,
        "amount": amount,
        "gl_suggestions": ["41000", "51000"],  # GL accounts to consider
        "vendor_flags": [],  # Vendor history flags
        "anomalies": [],  # Amount anomalies
        "confidence": 0.85,
        "requires_manual_review": False,
    }
