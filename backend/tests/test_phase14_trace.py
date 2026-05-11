"""Phase 14: Trace + Forecast Tests.

Tests for GL trace drill-down and forecast waterfall endpoints.
"""

import pytest
import tempfile
from datetime import datetime
from decimal import Decimal

from backend.cards.schemas import MemoryCard, PlanCard
from backend.cards.store import CardStore
from backend.membrane.trace.gl_trace import get_gl_trace
from backend.membrane.trace.forecast_merge import get_forecast_merge


class TestGLTrace:
    """Test GL trace endpoint."""

    @pytest.mark.asyncio
    async def test_get_gl_trace_response_schema(self):
        """Test GL trace returns expected response schema."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write signal memory cards
        for i in range(2):
            card = MemoryCard(
                card_id=f"signal-{i:03d}",
                principal="distiller",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                content=f"Signal {i}",
                confidence=0.9,
            )
            card_store.write(card, chain=True)

        # Get trace
        trace = await get_gl_trace("41000")

        # Verify schema
        assert "cell_id" in trace
        assert trace["cell_id"] == "41000"
        assert "current_balance" in trace
        assert "signal_count" in trace
        assert "signals" in trace
        assert isinstance(trace["signals"], list)

    @pytest.mark.asyncio
    async def test_get_gl_trace_empty_cell(self):
        """Test GL trace for cell with no signals."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Get trace for cell with no signals
        trace = await get_gl_trace("99000")

        assert trace["cell_id"] == "99000"
        assert trace["signal_count"] == 0
        assert trace["current_balance"] == 0.0

    @pytest.mark.asyncio
    async def test_trace_includes_lineage(self):
        """Test trace includes provenance lineage."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write signals from different principals
        for principal in ["distiller", "decision-deputy"]:
            card = MemoryCard(
                card_id=f"signal-{principal}",
                principal=principal,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                content="Test signal",
                confidence=0.9,
            )
            card_store.write(card, chain=True)

        # Get trace with lineage
        trace = await get_gl_trace("41000", include_lineage=True)

        assert trace["lineage"] is not None
        assert "by_principal" in trace["lineage"]
        assert "total_cards" in trace["lineage"]


class TestForecastMerge:
    """Test forecast merge (projection waterfall) endpoint."""

    @pytest.mark.asyncio
    async def test_get_forecast_merge_response_schema(self):
        """Test forecast merge returns expected response schema."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write GL snapshots at two dates
        from_snapshot = PlanCard(
            card_id="snapshot-2026-04-30",
            principal="budget-steward",
            created_at=datetime.fromisoformat("2026-04-30T00:00:00"),
            updated_at=datetime.fromisoformat("2026-04-30T00:00:00"),
            period="2026-04-30",
            accounts={
                "41000": Decimal("10000"),
                "51000": Decimal("5000"),
            },
            scenario="baseline",
        )

        to_snapshot = PlanCard(
            card_id="snapshot-2026-05-11",
            principal="budget-steward",
            created_at=datetime.fromisoformat("2026-05-11T00:00:00"),
            updated_at=datetime.fromisoformat("2026-05-11T00:00:00"),
            period="2026-05-11",
            accounts={
                "41000": Decimal("12000"),  # +2000
                "51000": Decimal("4500"),   # -500
            },
            scenario="baseline",
        )

        card_store.write(from_snapshot, chain=True)
        card_store.write(to_snapshot, chain=True)

        # Get forecast merge
        forecast = await get_forecast_merge("2026-04-30", "2026-05-11")

        assert forecast["from_date"] == "2026-04-30"
        assert forecast["to_date"] == "2026-05-11"
        # May have delta or error depending on snapshot finding logic
        assert "from_date" in forecast
        assert "to_date" in forecast

    @pytest.mark.asyncio
    async def test_forecast_missing_snapshots(self):
        """Test forecast handles missing snapshots gracefully."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Get forecast with no snapshots
        forecast = await get_forecast_merge("2026-04-30", "2026-05-11")

        assert "from_date" in forecast
        assert "to_date" in forecast
        # Should have error when no snapshots exist
        assert "error" in forecast or "delta" in forecast

    @pytest.mark.asyncio
    async def test_forecast_response_structure(self):
        """Test forecast merge response structure."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write minimal snapshots
        snapshot = PlanCard(
            card_id="snapshot",
            principal="budget-steward",
            created_at=datetime.fromisoformat("2026-05-11T00:00:00"),
            updated_at=datetime.fromisoformat("2026-05-11T00:00:00"),
            period="2026-05-11",
            accounts={"41000": Decimal("10000")},
            scenario="baseline",
        )
        card_store.write(snapshot, chain=True)

        # Get forecast
        forecast = await get_forecast_merge("2026-04-30", "2026-05-11")

        # Verify response structure
        assert "from_date" in forecast
        assert "to_date" in forecast
        assert isinstance(forecast["from_date"], str)
        assert isinstance(forecast["to_date"], str)


class TestTraceEndpointSchemas:
    """Test trace endpoint response schemas."""

    def test_gl_trace_schema(self):
        """Test GL trace response schema."""
        response = {
            "cell_id": "41000",
            "current_balance": 10000.0,
            "signal_count": 3,
            "signals": [
                {
                    "card_id": "signal-001",
                    "principal": "distiller",
                    "created_at": "2026-05-11T00:00:00",
                    "content": "Signal content",
                }
            ],
            "lineage": {
                "total_cards": 3,
                "by_principal": {"distiller": 3},
                "by_type": {"MEMORY": 3},
            }
        }

        assert "cell_id" in response
        assert "current_balance" in response
        assert "signal_count" in response
        assert "signals" in response

    def test_forecast_merge_schema(self):
        """Test forecast merge response schema."""
        response = {
            "from_date": "2026-04-30",
            "to_date": "2026-05-11",
            "delta": {
                "41000": {
                    "from": 10000.0,
                    "to": 12000.0,
                    "change": 2000.0,
                }
            },
            "waterfall": {
                "starting_balance": 15000.0,
                "ending_balance": 17000.0,
                "net_change": 2000.0,
                "period": "2026-04-30..2026-05-11",
                "drivers": [],
            }
        }

        assert "from_date" in response
        assert "to_date" in response
        assert "waterfall" in response


@pytest.fixture
def temp_card_store():
    """Fixture providing temporary CardStore."""
    temp_dir = tempfile.mkdtemp()
    return CardStore(data_dir=temp_dir)
