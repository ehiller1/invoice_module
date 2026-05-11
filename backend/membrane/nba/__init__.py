"""Phase 13: NBA Layer — Next Best Action Generation with CrewAI.

Analyst, Recommender, and Risk-Assessor agents with consumer group subscriber.
Generates and persists Recommendation Cards.
"""

from backend.membrane.nba.crew import NBACrewFactory
from backend.membrane.nba.consumer import nba_consumer_runner
from backend.membrane.nba.recommendation_card import (
    RecommendationCard,
    RecommendationPriority,
    RecommendationStatus,
)

__all__ = [
    "NBACrewFactory",
    "nba_consumer_runner",
    "RecommendationCard",
    "RecommendationPriority",
    "RecommendationStatus",
]
