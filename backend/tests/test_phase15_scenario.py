"""Phase 15: Scenario Simulator + Operations Council Tests.

Tests for what-if scenario simulation and KPI dashboard.
"""

import pytest
import tempfile
from datetime import datetime
from decimal import Decimal

from backend.cards.schemas import MemoryCard, PlanCard
from backend.cards.store import CardStore
from backend.membrane.scenario.simulator import (
    simulate_scenario,
    get_scenario,
    list_scenarios,
)
from backend.membrane.scenario.operations_council import (
    get_council_kpis,
    get_queue_status,
)
from backend.membrane.scenario.scenario_card import ScenarioType, ScenarioStatus


class TestScenarioSimulator:
    """Test scenario simulation engine."""

    @pytest.mark.asyncio
    async def test_simulate_scenario_baseline(self, temp_card_store):
        """Test baseline scenario simulation."""
        # Write base GL snapshot
        base_plan = PlanCard(
            card_id="plan-baseline",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={
                "41000": Decimal("10000"),
                "51000": Decimal("5000"),
                "61000": Decimal("2000"),
            },
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        # Simulate scenario: reduce 41000 by 10%
        result = await simulate_scenario(
            scenario_name="Reduce GL 41000 by 10%",
            scenario_type=ScenarioType.CUSTOM,
            assumptions={"reduction_pct": 10},
            changes={
                "41000": Decimal("-1000"),  # 10% of 10000
            },
        )

        # Verify structure
        assert result["scenario_id"].startswith("scenario-")
        assert result["name"] == "Reduce GL 41000 by 10%"
        assert result["base_gl"]["41000"] == 10000.0
        assert result["projected_gl"]["41000"] == 9000.0
        assert result["changes"]["41000"] == -1000.0

        # Verify impact analysis
        assert "impact_summary" in result
        assert result["impact_summary"]["total_base_gl"] == 17000.0
        assert result["impact_summary"]["total_projected_gl"] == 16000.0
        assert result["impact_summary"]["net_change"] == -1000.0

    @pytest.mark.asyncio
    async def test_simulate_scenario_optimistic(self, temp_card_store):
        """Test optimistic scenario (revenue increase)."""
        # Write base GL
        base_plan = PlanCard(
            card_id="plan-base",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={
                "41000": Decimal("10000"),
                "51000": Decimal("5000"),
            },
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        # Optimistic scenario: 20% revenue increase
        result = await simulate_scenario(
            scenario_name="20% Revenue Growth",
            scenario_type=ScenarioType.OPTIMISTIC,
            assumptions={"growth_rate": 0.20},
            changes={
                "51000": Decimal("1000"),
            },
        )

        assert result["projected_gl"]["51000"] == 6000.0
        assert result["impact_summary"]["net_change"] == 1000.0

    @pytest.mark.asyncio
    async def test_simulate_scenario_pessimistic(self, temp_card_store):
        """Test pessimistic scenario (expense overrun)."""
        # Write base GL
        base_plan = PlanCard(
            card_id="plan-base",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={
                "41000": Decimal("10000"),
            },
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        # Pessimistic scenario: 15% expense overrun
        result = await simulate_scenario(
            scenario_name="15% Expense Overrun",
            scenario_type=ScenarioType.PESSIMISTIC,
            assumptions={"overrun_pct": 0.15},
            changes={
                "41000": Decimal("1500"),
            },
        )

        assert result["projected_gl"]["41000"] == 11500.0
        assert result["impact_summary"]["variance_pct"] == 15.0

    @pytest.mark.asyncio
    async def test_get_scenario_by_id(self, temp_card_store):
        """Test retrieving scenario by ID."""
        # Create a scenario
        base_plan = PlanCard(
            card_id="plan-base",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={"41000": Decimal("10000")},
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        result = await simulate_scenario(
            scenario_name="Test Scenario",
            scenario_type=ScenarioType.CUSTOM,
            assumptions={},
            changes={"41000": Decimal("-500")},
        )

        scenario_id = result["scenario_id"]

        # Retrieve it
        retrieved = await get_scenario(scenario_id)
        assert retrieved is not None
        assert retrieved.get("scenario_id") == scenario_id

    @pytest.mark.asyncio
    async def test_list_scenarios(self, temp_card_store):
        """Test listing all scenarios."""
        # Create base GL
        base_plan = PlanCard(
            card_id="plan-base",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={"41000": Decimal("10000")},
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        # Create multiple scenarios
        for i in range(3):
            await simulate_scenario(
                scenario_name=f"Scenario {i}",
                scenario_type=ScenarioType.CUSTOM,
                assumptions={},
                changes={"41000": Decimal(str(-100 * (i + 1)))},
            )

        # List scenarios
        result = await list_scenarios(limit=10)
        assert "scenarios" in result
        assert "total" in result
        assert result["total"] >= 3

    @pytest.mark.asyncio
    async def test_scenario_impact_analysis(self, temp_card_store):
        """Test impact analysis calculations."""
        # Create detailed base GL
        base_plan = PlanCard(
            card_id="plan-base",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-11",
            accounts={
                "41000": Decimal("10000"),
                "41100": Decimal("5000"),
                "51000": Decimal("3000"),
            },
            scenario="baseline",
        )
        temp_card_store.write(base_plan, chain=True)

        # Simulate changes to multiple accounts
        result = await simulate_scenario(
            scenario_name="Multi-Account Changes",
            scenario_type=ScenarioType.CUSTOM,
            assumptions={},
            changes={
                "41000": Decimal("-1000"),
                "41100": Decimal("500"),
            },
        )

        impact = result["impact_summary"]
        assert impact["affected_accounts"] == 2  # 41000 and 41100 changed
        assert impact["total_base_gl"] == 18000.0
        assert impact["total_projected_gl"] == 17500.0
        assert impact["net_change"] == -500.0
        # Check variance_pct with tolerance for floating point precision
        assert abs(impact["variance_pct"] - (-2.7777777777777777)) < 0.0001


class TestOperationsCouncil:
    """Test Operations Council KPI dashboard."""

    @pytest.mark.asyncio
    async def test_get_council_kpis_structure(self, temp_card_store):
        """Test KPI dashboard returns expected structure."""
        # Get KPIs (should work even with empty store)
        kpis = await get_council_kpis()

        # Verify structure
        assert "timestamp" in kpis
        assert "exception_metrics" in kpis
        assert "policy_violations" in kpis
        assert "budget_metrics" in kpis
        assert "queue_health" in kpis
        assert "operational_risk_score" in kpis

    @pytest.mark.asyncio
    async def test_council_kpis_with_exceptions(self, temp_card_store):
        """Test KPI calculations with exception signals."""
        # Write exception signals
        for i in range(3):
            exception = MemoryCard(
                card_id=f"exception-{i:03d}",
                principal="distiller",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                content=f"Exception: Budget variance in account 41{i:03d}",
                confidence=0.9,
            )
            temp_card_store.write(exception, chain=True)

        # Get KPIs
        kpis = await get_council_kpis()

        assert kpis["exception_metrics"]["total_count"] == 3
        assert kpis["operational_risk_score"] in ["low", "medium", "high"]

    @pytest.mark.asyncio
    async def test_council_kpis_with_violations(self, temp_card_store):
        """Test KPI calculations with policy violations."""
        # Write policy violation signals
        for i in range(2):
            violation = MemoryCard(
                card_id=f"violation-{i:03d}",
                principal="distiller",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                content=f"Policy violation: Unapproved expense in fund {i}",
                confidence=0.95,
            )
            temp_card_store.write(violation, chain=True)

        # Get KPIs
        kpis = await get_council_kpis()

        assert kpis["policy_violations"]["total_count"] == 2

    @pytest.mark.asyncio
    async def test_queue_status_structure(self, temp_card_store):
        """Test queue status returns expected structure."""
        # Get queue status
        queue = await get_queue_status()

        # Verify structure
        assert "timestamp" in queue
        assert "exceptions" in queue
        assert "policy_violations" in queue
        assert "questions_pending" in queue
        assert "recommendations" in queue

    @pytest.mark.asyncio
    async def test_council_period_filtering(self, temp_card_store):
        """Test KPI dashboard filters by period."""
        # Write signals with various timestamps
        exception = MemoryCard(
            card_id="exception-001",
            principal="distiller",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Recent exception",
            confidence=0.9,
        )
        temp_card_store.write(exception, chain=True)

        # Get KPIs with 7-day lookback
        kpis_7d = await get_council_kpis(period_days=7)
        assert "exception_metrics" in kpis_7d

        # Get KPIs with 1-day lookback
        kpis_1d = await get_council_kpis(period_days=1)
        assert "exception_metrics" in kpis_1d


class TestScenarioSchemas:
    """Test scenario schemas and types."""

    def test_scenario_type_enum(self):
        """Test ScenarioType enum."""
        assert ScenarioType.BASELINE.value == "baseline"
        assert ScenarioType.OPTIMISTIC.value == "optimistic"
        assert ScenarioType.PESSIMISTIC.value == "pessimistic"
        assert ScenarioType.CUSTOM.value == "custom"

    def test_scenario_status_enum(self):
        """Test ScenarioStatus enum."""
        assert ScenarioStatus.DRAFT.value == "draft"
        assert ScenarioStatus.APPROVED.value == "approved"
        assert ScenarioStatus.EXECUTED.value == "executed"
        assert ScenarioStatus.ARCHIVED.value == "archived"


@pytest.fixture
def temp_card_store(monkeypatch):
    """Fixture providing temporary CardStore with mocked get_card_store."""
    temp_dir = tempfile.mkdtemp()
    store = CardStore(data_dir=temp_dir)

    # Mock get_card_store to return our test instance
    import backend.cards.store as store_module
    monkeypatch.setattr(store_module, "_card_store", store)

    return store
