"""Phase 13: NBA Consumer Group Subscriber.

Listens to perturbation channels and invokes NBA crew to generate recommendations.
Writes Recommendation Cards to Card Store.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict

from backend.membrane.transport.base import MessageTransport
from backend.membrane.transport.channels import Channel
from backend.cards.store import get_card_store
from backend.membrane.nba.recommendation_card import (
    RecommendationCard,
    RecommendationPriority,
    RecommendationStatus,
)
from backend.membrane.nba.crew import NBACrewFactory

logger = logging.getLogger(__name__)


async def nba_consumer_runner(
    transport: MessageTransport,
    channels: list[str],
) -> None:
    """NBA consumer group runner — listens to perturbations and generates recommendations.

    Args:
        transport: MessageTransport for subscribing to channels
        channels: List of perturbation channels to monitor
    """
    logger.info(
        f"NBA Consumer started, monitoring {len(channels)} channel(s)"
    )

    # Subscribe to channels
    for channel in channels:
        await transport.ensure_group(channel, "nba-consumer-group")

    card_store = get_card_store()
    counter = 0

    while True:
        try:
            # Consume messages from subscribed channels
            for channel in channels:
                messages = await transport.consume_batch(
                    channel,
                    "nba-consumer-group",
                    "nba-consumer",
                    count=5,
                    block_ms=1000,
                )

                for msg in messages:
                    logger.info(f"NBA processing signal from {channel}: {msg.payload}")

                    # Determine recommendation trigger type from channel
                    trigger_type = _channel_to_trigger_type(channel)

                    # Build context from Card Store
                    context = await _build_nba_context(card_store, trigger_type)

                    # Invoke NBA crew
                    recommendations = await _generate_recommendations(
                        trigger_type,
                        context,
                        msg.payload,
                    )

                    # Write recommendation cards to Card Store
                    if recommendations:
                        for rec_data in recommendations:
                            await _write_recommendation_card(card_store, rec_data)

                    # Acknowledge message
                    await transport.ack(channel, "nba-consumer-group", msg.delivery_id)
                    counter += 1

            await asyncio.sleep(5)

        except Exception as e:
            logger.error(f"NBA Consumer error: {e}")
            # Continue running despite errors
            await asyncio.sleep(5)


async def _build_nba_context(card_store: Any, trigger_type: str) -> Dict[str, Any]:
    """Build context for NBA crew from Card Store.

    Queries recent decisions, budget projections, policy violations.

    Args:
        card_store: CardStore instance (singleton)
        trigger_type: Type of triggering signal
    """

    context = {
        "trigger_type": trigger_type,
        "recent_decisions": [],
        "budget_projections": [],
        "policy_violations": [],
        "payment_exceptions": [],
    }

    # Query for recent cabinet decisions
    all_cards = card_store.query_by_principal("decision-deputy")
    context["recent_decisions"] = all_cards[-5:] if all_cards else []

    # Query for budget projections
    projections = card_store.query_by_principal("budget-steward")
    context["budget_projections"] = projections[-3:] if projections else []

    # Query for screening notes from intake-specialist
    screenings = card_store.query_by_principal("intake-specialist")
    context["policy_violations"] = screenings[-5:] if screenings else []

    logger.info(f"Built NBA context: {len(context['recent_decisions'])} decisions, "
                f"{len(context['budget_projections'])} projections")

    return context


async def _generate_recommendations(
    trigger_type: str,
    context: Dict[str, Any],
    signal_payload: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Generate recommendations using NBA crew.

    Returns list of recommendation data dicts.
    """
    logger.info(f"NBA crew generating recommendations for {trigger_type}")

    # Invoke crew
    crew_result = await NBACrewFactory.invoke_crew(
        trigger_type=trigger_type,
        context=context,
    )

    if crew_result["status"] != "success":
        logger.error(f"NBA crew failed: {crew_result.get('error')}")
        return []

    # Parse crew output and extract recommendations
    # For now, return placeholder recommendations
    # In production, parse crew.kickoff() output JSON
    recommendations = _parse_crew_output(crew_result.get("recommendations", ""))

    logger.info(f"NBA generated {len(recommendations)} recommendations")
    return recommendations


def _parse_crew_output(output: str) -> list[Dict[str, Any]]:
    """Parse CrewAI output into recommendation dicts.

    CrewAI crew.kickoff() returns JSON output. Parse it to extract recommendations.

    Expected format:
    {
        "status": "success",
        "recommendations": [
            {
                "recommendation_id": "...",
                "title": "...",
                "description": "...",
                ...
            }
        ]
    }
    """
    import json

    if not output or not isinstance(output, str):
        logger.warning(f"No crew output to parse: {output}")
        return []

    try:
        # Try parsing as JSON
        if isinstance(output, str):
            # If it's a raw string, try to extract JSON
            # Some crew outputs wrap JSON in markdown code blocks
            if "```json" in output:
                start = output.find("```json") + 7
                end = output.find("```", start)
                json_str = output[start:end].strip()
            elif "```" in output:
                start = output.find("```") + 3
                end = output.find("```", start)
                json_str = output[start:end].strip()
            else:
                json_str = output

            data = json.loads(json_str)
        else:
            data = output

        # Extract recommendations from the parsed data
        if isinstance(data, dict):
            recommendations = data.get("recommendations", [])
            if not isinstance(recommendations, list):
                # If recommendations is a single dict, wrap it
                recommendations = [recommendations]
        elif isinstance(data, list):
            recommendations = data
        else:
            recommendations = []

        logger.info(f"Parsed {len(recommendations)} recommendations from crew output")
        return recommendations

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse crew output as JSON: {e}")
        logger.debug(f"Raw output: {output}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error parsing crew output: {e}")
        return []


async def _write_recommendation_card(
    card_store,
    rec_data: Dict[str, Any],
) -> None:
    """Write recommendation card to Card Store."""
    try:
        from decimal import Decimal

        # Create Recommendation Card
        card = RecommendationCard(
            card_id=rec_data.get("card_id", f"rec-{datetime.utcnow().timestamp()}"),
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id=rec_data.get("recommendation_id", "unknown"),
            title=rec_data.get("title", ""),
            description=rec_data.get("description", ""),
            trigger_type=rec_data.get("trigger_type", "unknown"),
            trigger_ids=rec_data.get("trigger_ids", []),
            projected_impact={
                k: Decimal(str(v))
                for k, v in rec_data.get("projected_impact", {}).items()
            },
            affected_accounts=rec_data.get("affected_accounts", []),
            affected_dimensions=rec_data.get("affected_dimensions", {}),
            confidence=float(rec_data.get("confidence", 0.5)),
            priority=RecommendationPriority(rec_data.get("priority", "medium")),
            risk_level=rec_data.get("risk_level", "medium"),
            risk_factors=rec_data.get("risk_factors", []),
            reasoning=rec_data.get("reasoning", ""),
            alternatives=rec_data.get("alternatives", []),
            prerequisites=rec_data.get("prerequisites", []),
            status=RecommendationStatus.PROPOSED,
        )

        card_store.write(card, chain=True)
        logger.info(f"Wrote recommendation card {card.card_id} to store")

    except Exception as e:
        logger.error(f"Failed to write recommendation card: {e}")


def _channel_to_trigger_type(channel: str) -> str:
    """Map channel name to recommendation trigger type."""
    mapping = {
        Channel.IMPACT_ADVISORY_BUDGET_THRESHOLD: "budget_overage",
        Channel.PASTORAL_PROPOSED_RESTRICTION_FLAGGED: "policy_violation",
        Channel.IMPACT_PROPOSED_PAYMENT_QUEUED: "payment_queued",
        Channel.STEWARDSHIP_PROPOSED_BUDGET_CHANGED: "budget_change",
    }
    return mapping.get(channel, "general_optimization")
