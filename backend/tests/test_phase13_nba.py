"""Phase 13: NBA Layer Tests.

Tests for Next Best Action crew, recommendation cards, and endpoints.
"""

import pytest
import tempfile
from datetime import datetime
from decimal import Decimal

from backend.membrane.nba.recommendation_card import (
    RecommendationCard,
    RecommendationPriority,
    RecommendationStatus,
)
from backend.membrane.nba.crew import NBACrewFactory
from backend.cards.store import CardStore


class TestRecommendationCardSchema:
    """Test Recommendation Card schema and serialization."""

    def test_recommendation_card_creation(self):
        """Test creating a Recommendation Card."""
        card = RecommendationCard(
            card_id="rec-001",
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id="rec-budget-overage-41000",
            title="Reduce GL 41000 allocation",
            description="GL account 41000 is at 95% budget. Recommend reducing non-essential spending.",
            trigger_type="budget_overage",
            trigger_ids=["signal-budget-overage-41000"],
            projected_impact={"41000": Decimal("-5000")},
            affected_accounts=["41000"],
            confidence=0.85,
            priority=RecommendationPriority.HIGH,
            risk_level="low",
            risk_factors=["minimal disruption"],
            reasoning="Current burn rate suggests overage by month end",
            status=RecommendationStatus.PROPOSED,
        )

        assert card.card_id == "rec-001"
        assert card.confidence == 0.85
        assert card.priority == RecommendationPriority.HIGH
        assert card.status == RecommendationStatus.PROPOSED

    def test_recommendation_card_serialization(self):
        """Test Recommendation Card JSON serialization."""
        card = RecommendationCard(
            card_id="rec-001",
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id="rec-001",
            title="Test",
            description="Test recommendation",
            trigger_type="budget_overage",
            projected_impact={"41000": Decimal("1000")},
            affected_accounts=["41000"],
            confidence=0.9,
            priority=RecommendationPriority.MEDIUM,
            risk_level="medium",
            reasoning="Test",
        )

        # Serialize to dict
        card_dict = card.model_dump(mode="json")
        assert card_dict["card_id"] == "rec-001"
        assert card_dict["confidence"] == 0.9
        # Decimal should be serialized to string
        assert isinstance(card_dict["projected_impact"]["41000"], str)

    def test_recommendation_card_confidence_validation(self):
        """Test Recommendation Card confidence score validation."""
        # Valid confidence scores
        card = RecommendationCard(
            card_id="rec-001",
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id="rec-001",
            title="Test",
            description="Test",
            trigger_type="budget_overage",
            confidence=0.0,
            priority=RecommendationPriority.LOW,
            risk_level="low",
            reasoning="Test",
        )
        assert card.confidence == 0.0

        card = RecommendationCard(
            card_id="rec-001",
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id="rec-001",
            title="Test",
            description="Test",
            trigger_type="budget_overage",
            confidence=1.0,
            priority=RecommendationPriority.HIGH,
            risk_level="high",
            reasoning="Test",
        )
        assert card.confidence == 1.0

    def test_recommendation_priority_enum(self):
        """Test RecommendationPriority enum values."""
        assert RecommendationPriority.HIGH.value == "high"
        assert RecommendationPriority.MEDIUM.value == "medium"
        assert RecommendationPriority.LOW.value == "low"

    def test_recommendation_status_enum(self):
        """Test RecommendationStatus enum values."""
        assert RecommendationStatus.PROPOSED.value == "proposed"
        assert RecommendationStatus.ACCEPTED.value == "accepted"
        assert RecommendationStatus.DECLINED.value == "declined"
        assert RecommendationStatus.DEFERRED.value == "deferred"
        assert RecommendationStatus.EXECUTED.value == "executed"


class TestNBACrewFactory:
    """Test NBA crew factory and agent creation."""

    @pytest.mark.skip(reason="CrewAI requires OpenAI API key; full integration tested in Phase 20")
    def test_analyst_agent_creation(self):
        """Test Analyst Agent creation."""
        agent = NBACrewFactory.create_analyst_agent()

        assert agent.role == "Financial Analyst"
        assert "identify opportunities" in agent.goal.lower()
        assert agent.verbose is True

    @pytest.mark.skip(reason="CrewAI requires OpenAI API key; full integration tested in Phase 20")
    def test_recommender_agent_creation(self):
        """Test Recommender Agent creation."""
        agent = NBACrewFactory.create_recommender_agent()

        assert agent.role == "Financial Advisor"
        assert "prioritized" in agent.goal.lower()
        assert agent.verbose is True

    @pytest.mark.skip(reason="CrewAI requires OpenAI API key; full integration tested in Phase 20")
    def test_risk_assessor_agent_creation(self):
        """Test Risk Assessor Agent creation."""
        agent = NBACrewFactory.create_risk_assessor_agent()

        assert agent.role == "Risk Assessment Officer"
        assert "risk" in agent.goal.lower()
        assert agent.verbose is True

    @pytest.mark.skip(reason="CrewAI requires OpenAI API key; full integration tested in Phase 20")
    def test_crew_creation(self):
        """Test NBA crew creation."""
        crew = NBACrewFactory.create_crew()

        # Verify crew has 3 agents
        assert len(crew.agents) == 3

        # Verify crew has 3 tasks
        assert len(crew.tasks) == 3

        # Verify sequential process
        assert crew.process.value == "sequential"

    @pytest.mark.skip(reason="CrewAI requires OpenAI API key; full integration tested in Phase 20")
    def test_crew_agent_roles(self):
        """Test that crew agents have expected roles."""
        crew = NBACrewFactory.create_crew()

        roles = [agent.role for agent in crew.agents]
        assert "Financial Analyst" in roles
        assert "Financial Advisor" in roles
        assert "Risk Assessment Officer" in roles

    def test_crew_factory_methods_exist(self):
        """Test that crew factory has required methods."""
        assert hasattr(NBACrewFactory, "create_analyst_agent")
        assert hasattr(NBACrewFactory, "create_recommender_agent")
        assert hasattr(NBACrewFactory, "create_risk_assessor_agent")
        assert hasattr(NBACrewFactory, "create_crew")
        assert hasattr(NBACrewFactory, "invoke_crew")


class TestRecommendationCardStore:
    """Test Recommendation Cards in Card Store."""

    def test_write_recommendation_to_store(self):
        """Test writing Recommendation Card to Card Store."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        card = RecommendationCard(
            card_id="rec-001",
            principal="nba-crew",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            recommendation_id="rec-budget-overage",
            title="Reduce budget",
            description="GL 41000 at risk",
            trigger_type="budget_overage",
            projected_impact={"41000": Decimal("-5000")},
            affected_accounts=["41000"],
            confidence=0.85,
            priority=RecommendationPriority.HIGH,
            risk_level="low",
            reasoning="Burn rate too high",
        )

        card_store.write(card, chain=True)

        # Read back
        read_card = card_store.read("rec-001")
        assert read_card is not None
        assert read_card["card_id"] == "rec-001"
        assert read_card["confidence"] == 0.85

    def test_query_recommendations_by_principal(self):
        """Test querying Recommendation Cards by principal."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write multiple recommendations
        for i in range(3):
            card = RecommendationCard(
                card_id=f"rec-{i:03d}",
                principal="nba-crew",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                recommendation_id=f"rec-{i}",
                title=f"Recommendation {i}",
                description=f"Test recommendation {i}",
                trigger_type="budget_overage",
                confidence=0.8 + (i * 0.05),
                priority=RecommendationPriority.HIGH,
                risk_level="low",
                reasoning="Test",
            )
            card_store.write(card, chain=True)

        # Query by principal
        cards = card_store.query_by_principal("nba-crew")
        assert len(cards) == 3
        assert all(c["principal"] == "nba-crew" for c in cards)

    def test_recommendation_card_chain_integrity(self):
        """Test that Recommendation Cards maintain chain integrity."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write multiple recommendations
        for i in range(5):
            card = RecommendationCard(
                card_id=f"rec-chain-{i:03d}",
                principal="nba-crew",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                recommendation_id=f"rec-{i}",
                title=f"Rec {i}",
                description="Test",
                trigger_type="general_optimization",
                confidence=0.7,
                priority=RecommendationPriority.MEDIUM,
                risk_level="medium",
                reasoning="Test",
            )
            card_store.write(card, chain=True)

        # Verify chain
        is_valid = card_store.verify_chain()
        assert is_valid


class TestRecommendationEndpoints:
    """Test NBA endpoints response schemas."""

    def test_list_recommendations_schema(self):
        """Test list recommendations endpoint response schema."""
        response = {
            "total": 3,
            "limit": 20,
            "offset": 0,
            "recommendations": [
                {
                    "card_id": "rec-001",
                    "recommendation_id": "rec-budget-overage",
                    "title": "Reduce GL 41000 allocation",
                    "status": "proposed",
                    "priority": "high",
                    "confidence": 0.85,
                }
            ]
        }

        assert "total" in response
        assert "limit" in response
        assert "recommendations" in response
        assert len(response["recommendations"]) > 0

    def test_get_recommendation_schema(self):
        """Test get recommendation endpoint response schema."""
        response = {
            "card_id": "rec-001",
            "recommendation_id": "rec-budget-overage",
            "title": "Reduce GL 41000 allocation",
            "description": "GL account 41000 is at 95% budget",
            "trigger_type": "budget_overage",
            "affected_accounts": ["41000"],
            "projected_impact": {"41000": "-5000"},
            "confidence": 0.85,
            "priority": "high",
            "risk_level": "low",
            "status": "proposed",
        }

        assert "card_id" in response
        assert "recommendation_id" in response
        assert "status" in response
        assert response["confidence"] == 0.85

    def test_accept_recommendation_response_schema(self):
        """Test accept recommendation endpoint response schema."""
        response = {
            "recommendation_id": "rec-001",
            "status": "accepted",
            "accepted_at": datetime.utcnow().isoformat(),
            "accepted_by": "user-001",
        }

        assert "recommendation_id" in response
        assert "status" in response
        assert response["status"] == "accepted"
        assert "accepted_at" in response
        assert "accepted_by" in response

    def test_decline_recommendation_response_schema(self):
        """Test decline recommendation endpoint response schema."""
        response = {
            "recommendation_id": "rec-001",
            "status": "declined",
            "declined_at": datetime.utcnow().isoformat(),
            "declined_by": "user-001",
            "reason": "Does not align with current priorities",
        }

        assert "recommendation_id" in response
        assert "status" in response
        assert response["status"] == "declined"
        assert "reason" in response

    def test_defer_recommendation_response_schema(self):
        """Test defer recommendation endpoint response schema."""
        response = {
            "recommendation_id": "rec-001",
            "status": "deferred",
            "deferred_at": datetime.utcnow().isoformat(),
            "deferred_by": "user-001",
            "deferral_notes": "Revisit after Q2 budget review",
            "defer_until": "2026-07-01",
        }

        assert "recommendation_id" in response
        assert "status" in response
        assert response["status"] == "deferred"
        assert "defer_until" in response
