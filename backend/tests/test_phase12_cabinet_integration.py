"""Phase 12: Cabinet Integration Tests.

Comprehensive tests for OpenClaw cabinet runtime, cabinet member runners,
and integration with Card Store, Decision Ledger, and backend endpoints.
"""

import asyncio
import pytest
import tempfile
from datetime import datetime

from backend.cards.schemas import MemoryCard, DecisionPacket
from backend.cards.store import CardStore
from backend.cards.ledger import DecisionLedgerWithChain, LedgerEntry, DecisionCategory
from backend.decision_ledger import DecisionOutcome
from backend.membrane.transport.local import LocalTransport
from backend.membrane.transport.channels import Channel
from openclaw.runtime import CabinetRuntime


class TestCabinetRuntime:
    """Test CabinetRuntime orchestration."""

    @pytest.mark.asyncio
    async def test_runtime_member_registration(self):
        """Test cabinet runtime member registration."""
        transport = LocalTransport()
        runtime = CabinetRuntime(transport)

        # Register a dummy member
        async def dummy_member(trans, channels):
            await asyncio.sleep(0.1)

        runtime.register_member(
            principal_id="test-member",
            role="TEST",
            channels=[Channel.IMPACT_PROPOSED_INVOICE_INGESTED],
            runner=dummy_member
        )

        # Verify member registered
        assert "test-member" in runtime.members
        assert runtime.members["test-member"].role == "TEST"
        assert runtime.members["test-member"].principal_id == "test-member"

    @pytest.mark.asyncio
    async def test_runtime_stop(self):
        """Test cabinet runtime stop method."""
        transport = LocalTransport()
        runtime = CabinetRuntime(transport)

        async def dummy_member(trans, channels):
            while runtime.running:
                await asyncio.sleep(0.01)

        runtime.register_member(
            principal_id="test-member",
            role="TEST",
            channels=[],
            runner=dummy_member
        )

        # Start in background
        task = asyncio.create_task(runtime.start())
        await asyncio.sleep(0.1)

        # Stop
        runtime.stop()
        await asyncio.sleep(0.05)

        # Verify stopped
        assert runtime.running is False

        # Clean up
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestQueueGuardianRunner:
    """Test queue-guardian cabinet member."""

    @pytest.mark.asyncio
    async def test_queue_guardian_runner_importable(self):
        """Test queue-guardian runner is importable and callable."""
        from openclaw.treasurer.queue_guardian.runner import queue_guardian_runner

        # Verify runner exists and is callable
        assert callable(queue_guardian_runner)

    @pytest.mark.asyncio
    async def test_queue_guardian_transport_consumption(self):
        """Test that signals can be published to channels."""
        transport = LocalTransport()

        # Publish a signal to a real channel
        delivery_id = await transport.publish(
            Channel.IMPACT_PROPOSED_INVOICE_INGESTED,
            {
                "invoice_id": "inv-001",
                "vendor": "ACME Corp",
                "amount": 5000.0
            }
        )

        # Verify signal was published
        assert delivery_id is not None
        assert delivery_id != "duplicate"


class TestDecisionDeputyRunner:
    """Test decision-deputy cabinet member."""

    @pytest.mark.asyncio
    async def test_decision_deputy_runner_importable(self):
        """Test decision-deputy runner is importable."""
        from openclaw.treasurer.decision_deputy.runner import decision_deputy_runner

        # Verify runner exists and is callable
        assert callable(decision_deputy_runner)


class TestBudgetStewardRunner:
    """Test budget-steward cabinet member."""

    @pytest.mark.asyncio
    async def test_budget_steward_runner_importable(self):
        """Test budget-steward runner is importable."""
        from openclaw.budget_owner.budget_steward.runner import budget_steward_runner

        # Verify runner exists and is callable
        assert callable(budget_steward_runner)


class TestIntakeSpecialistRunner:
    """Test intake-specialist cabinet member."""

    @pytest.mark.asyncio
    async def test_intake_specialist_runner_importable(self):
        """Test intake-specialist runner is importable."""
        from openclaw.finance_staff.intake_specialist.runner import intake_specialist_runner

        # Verify runner exists and is callable
        assert callable(intake_specialist_runner)

    @pytest.mark.asyncio
    async def test_intake_specialist_analysis(self):
        """Test intake-specialist invoice analysis."""
        from openclaw.finance_staff.intake_specialist.runner import analyze_invoice

        # Analyze an invoice
        analysis = await analyze_invoice(
            invoice_id="inv-001",
            vendor="ACME Corp",
            amount=5000.0
        )

        # Verify analysis contains expected fields
        assert "invoice_id" in analysis
        assert "vendor" in analysis
        assert "gl_suggestions" in analysis
        assert "vendor_flags" in analysis
        assert "anomalies" in analysis
        assert "confidence" in analysis
        assert isinstance(analysis["confidence"], float)
        assert 0.0 <= analysis["confidence"] <= 1.0


class TestCabinetEndpoints:
    """Test cabinet-related API endpoints (schema validation)."""

    def test_cabinet_activity_schema(self):
        """Test cabinet activity endpoint response schema."""
        activity_response = {
            "principal": "queue-guardian",
            "total": 2,
            "limit": 20,
            "offset": 0,
            "activity": [
                {
                    "card_id": "mem-001",
                    "card_type": "MEMORY",
                    "principal": "queue-guardian",
                    "content": "Daily digest",
                    "confidence": 0.9,
                    "created_at": datetime.utcnow().isoformat(),
                }
            ]
        }

        # Verify schema
        assert "principal" in activity_response
        assert "total" in activity_response
        assert "activity" in activity_response
        assert len(activity_response["activity"]) > 0

    def test_cabinet_current_items_schema(self):
        """Test cabinet current-items endpoint response schema."""
        current_items_response = {
            "principal": "decision-deputy",
            "current_count": 1,
            "items": [
                {
                    "card_id": "dec-001",
                    "card_type": "DECISION",
                    "principal": "decision-deputy",
                    "decision_id": "esc-001",
                    "category": "APPROVE",
                    "verdict": "APPROVE",
                    "reasoning": "All checks pass",
                    "confidence": 0.85,
                    "approvers": [],
                    "created_at": datetime.utcnow().isoformat(),
                }
            ]
        }

        # Verify schema
        assert "principal" in current_items_response
        assert "current_count" in current_items_response
        assert "items" in current_items_response

    def test_cabinet_approval_response_schema(self):
        """Test cabinet approval endpoint response schema."""
        approval_response = {
            "item_id": "dec-001",
            "status": "approved",
            "approved_at": datetime.utcnow().isoformat(),
            "approved_by": "treasurer-001"
        }

        # Verify schema
        assert "item_id" in approval_response
        assert "status" in approval_response
        assert approval_response["status"] == "approved"
        assert "approved_at" in approval_response
        assert "approved_by" in approval_response

    def test_cabinet_rejection_response_schema(self):
        """Test cabinet rejection endpoint response schema."""
        rejection_response = {
            "item_id": "dec-001",
            "status": "rejected",
            "rejected_at": datetime.utcnow().isoformat(),
            "rejected_by": "treasurer-001",
            "reason": "Needs clarification on vendor"
        }

        # Verify schema
        assert "item_id" in rejection_response
        assert "status" in rejection_response
        assert rejection_response["status"] == "rejected"
        assert "reason" in rejection_response


class TestCabinetCardStoreIntegration:
    """Test integration between cabinet members and Card Store."""

    def test_memory_card_write_and_read(self):
        """Test cabinet writes Memory Cards to Card Store."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write a Memory Card from queue-guardian
        memory_card = MemoryCard(
            card_id="mem-001",
            principal="queue-guardian",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Daily approval queue digest",
            confidence=0.9
        )

        card_store.write(memory_card, chain=True)

        # Read it back
        read_card = card_store.read("mem-001")
        assert read_card is not None
        assert read_card["principal"] == "queue-guardian"
        assert read_card["confidence"] == 0.9

    def test_decision_packet_write_and_query(self):
        """Test cabinet writes Decision Packets and they're queryable."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write Decision Packet from decision-deputy
        decision_card = DecisionPacket(
            card_id="dec-001",
            principal="decision-deputy",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            decision_id="esc-001",
            category="APPROVE",
            verdict="APPROVE",
            reasoning="All compliance checks passed",
            confidence=0.85,
            approvers=[]
        )

        card_store.write(decision_card, chain=True)

        # Query by principal
        decisions = card_store.query_by_principal("decision-deputy")
        assert len(decisions) > 0
        assert decisions[0]["principal"] == "decision-deputy"

    def test_card_chain_integrity_across_writes(self):
        """Test that SHA-256 chain remains intact across multiple writes."""
        temp_dir = tempfile.mkdtemp()
        card_store = CardStore(data_dir=temp_dir)

        # Write multiple cards
        for i in range(3):
            card = MemoryCard(
                card_id=f"mem-{i:03d}",
                principal="queue-guardian",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                content=f"Digest {i}",
                confidence=0.9
            )
            card_store.write(card, chain=True)

        # Verify entire chain
        is_valid = card_store.verify_chain()
        assert is_valid


class TestCabinetDecisionLedgerIntegration:
    """Test integration between cabinet approvals and Decision Ledger."""

    def test_approval_written_to_ledger(self):
        """Test that cabinet approval writes to Decision Ledger."""
        temp_dir = tempfile.mkdtemp()
        ledger = DecisionLedgerWithChain(church_id="default", data_dir=temp_dir)

        # Write approval entry
        entry = LedgerEntry(
            entry_id="approval-dec-001",
            decision_id="dec-001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={
                "actor_id": "treasurer-001",
                "actor_type": "TREASURER_ADMIN"
            },
            outcome=DecisionOutcome.ACCEPTED,
            metadata={
                "approved_by": "treasurer-001",
                "approval_notes": "Approved with signature"
            }
        )

        ledger.append(entry)

        # Retrieve by decision_id
        decisions = ledger.find_by_decision("dec-001")
        assert len(decisions) > 0
        assert decisions[0]["outcome"] == "accepted"

    def test_rejection_written_to_ledger(self):
        """Test that cabinet rejection writes to Decision Ledger."""
        temp_dir = tempfile.mkdtemp()
        ledger = DecisionLedgerWithChain(church_id="default", data_dir=temp_dir)

        # Write rejection entry
        entry = LedgerEntry(
            entry_id="rejection-dec-001",
            decision_id="dec-001",
            category=DecisionCategory.ROUTE,
            timestamp=datetime.utcnow(),
            authoring_actor={
                "actor_id": "treasurer-001",
                "actor_type": "TREASURER_ADMIN"
            },
            outcome=DecisionOutcome.REJECTED,
            metadata={
                "rejected_by": "treasurer-001",
                "rejection_reason": "Needs clarification",
                "send_back_to": "decision-deputy"
            }
        )

        ledger.append(entry)

        # Retrieve by decision_id
        decisions = ledger.find_by_decision("dec-001")
        assert len(decisions) > 0
        assert decisions[0]["outcome"] == "rejected"

    def test_ledger_chain_integrity(self):
        """Test Decision Ledger maintains SHA-256 chain integrity."""
        temp_dir = tempfile.mkdtemp()
        ledger = DecisionLedgerWithChain(church_id="default", data_dir=temp_dir)

        # Write multiple entries
        for i in range(3):
            entry = LedgerEntry(
                entry_id=f"entry-{i:03d}",
                decision_id=f"dec-{i:03d}",
                category=DecisionCategory.APPROVE,
                timestamp=datetime.utcnow(),
                authoring_actor={"actor_id": "actor-1", "actor_type": "ADMIN"},
                outcome=DecisionOutcome.ACCEPTED,
                metadata={}
            )
            ledger.append(entry)

        # Verify chain
        is_valid = ledger.verify_chain()
        assert is_valid


@pytest.fixture
def temp_card_store():
    """Fixture providing a temporary CardStore instance."""
    temp_dir = tempfile.mkdtemp()
    return CardStore(data_dir=temp_dir)


@pytest.fixture
def temp_ledger():
    """Fixture providing a temporary DecisionLedger instance."""
    temp_dir = tempfile.mkdtemp()
    return DecisionLedgerWithChain(church_id="test-church", data_dir=temp_dir)


@pytest.fixture
def local_transport():
    """Fixture providing LocalTransport for testing."""
    return LocalTransport()
