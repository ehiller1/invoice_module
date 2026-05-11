"""Phase 10: Cards + Ledger + Decision Governance (25 tests)."""

import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.cards.schemas import (
    MemoryCard,
    PlanCard,
    DecisionPacket,
)
from backend.cards.store import CardStore
from backend.cards.ledger import DecisionLedgerWithChain
from backend.tools.guider_feedback_store import GuiderFeedbackStore
from backend.decision_ledger import DecisionCategory, LedgerEntry, DecisionOutcome


class TestCardStore:
    """Test CardStore unified persistence."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def store(self, temp_dir):
        """Create CardStore with temp directory."""
        return CardStore(temp_dir)

    def test_write_and_read_memory_card(self, store):
        """Test writing and reading a MemoryCard."""
        card = MemoryCard(
            card_id="mem001",
            principal="queue-guardian",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Daily digest: 5 escalations, 2 budget warnings",
            confidence=0.95,
        )

        card_id = store.write(card)
        assert card_id == "mem001"

        read_card = store.read("mem001")
        assert read_card is not None
        assert read_card["principal"] == "queue-guardian"
        assert read_card["card_type"] == "memory"
        assert read_card["confidence"] == 0.95

    def test_write_and_read_plan_card(self, store):
        """Test writing and reading a PlanCard."""
        card = PlanCard(
            card_id="plan001",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05-Q2",
            accounts={
                "10000": Decimal("50000.00"),
                "20000": Decimal("30000.00"),
            },
            assumptions={"inflation_rate": 0.025},
            scenario="baseline",
        )

        card_id = store.write(card)
        assert card_id == "plan001"

        read_card = store.read("plan001")
        assert read_card is not None
        assert read_card["period"] == "2026-05-Q2"
        assert read_card["card_type"] == "plan"

    def test_write_and_read_decision_packet(self, store):
        """Test writing and reading a DecisionPacket."""
        card = DecisionPacket(
            card_id="dec001",
            principal="drafting_agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            decision_id="ledger_entry_001",
            category="APPROVE",
            verdict="APPROVE",
            reasoning="Vendor approved, amount within bounds",
            evidence_refs=["evt001", "evt002"],
            confidence=0.92,
            approvers=["treasury_user_1"],
        )

        card_id = store.write(card)
        assert card_id == "dec001"

        read_card = store.read("dec001")
        assert read_card is not None
        assert read_card["category"] == "APPROVE"
        assert read_card["verdict"] == "APPROVE"

    def test_query_by_type(self, store):
        """Test querying cards by type."""
        mem_card = MemoryCard(
            card_id="mem001",
            principal="cabinet",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Memory 1",
        )
        plan_card = PlanCard(
            card_id="plan001",
            principal="cabinet",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05",
            accounts={},
        )

        store.write(mem_card)
        store.write(plan_card)

        memory_cards = store.query_by_type("memory")
        assert len(memory_cards) == 1
        assert memory_cards[0]["card_id"] == "mem001"

        plan_cards = store.query_by_type("plan")
        assert len(plan_cards) == 1
        assert plan_cards[0]["card_id"] == "plan001"

    def test_query_by_principal(self, store):
        """Test querying cards by principal (author)."""
        card1 = MemoryCard(
            card_id="mem001",
            principal="queue-guardian",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Memory from queue-guardian",
        )
        card2 = MemoryCard(
            card_id="mem002",
            principal="decision-deputy",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Memory from decision-deputy",
        )

        store.write(card1)
        store.write(card2)

        guardian_cards = store.query_by_principal("queue-guardian")
        assert len(guardian_cards) == 1
        assert guardian_cards[0]["principal"] == "queue-guardian"

    def test_query_by_period(self, store):
        """Test querying PlanCards by period."""
        card1 = PlanCard(
            card_id="plan001",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-05",
            accounts={"10000": Decimal("1000.00")},
        )
        card2 = PlanCard(
            card_id="plan002",
            principal="budget-steward",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            period="2026-06",
            accounts={"10000": Decimal("1100.00")},
        )

        store.write(card1)
        store.write(card2)

        may_cards = store.query_by_period("2026-05")
        assert len(may_cards) == 1
        assert may_cards[0]["period"] == "2026-05"

    def test_query_by_category(self, store):
        """Test querying DecisionPackets by category."""
        card1 = DecisionPacket(
            card_id="dec001",
            principal="drafting_agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            decision_id="ld001",
            category="APPROVE",
            verdict="APPROVE",
            reasoning="Approved",
        )
        card2 = DecisionPacket(
            card_id="dec002",
            principal="drafting_agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            decision_id="ld002",
            category="OVERRIDE",
            verdict="APPROVE",
            reasoning="Override due to exception",
        )

        store.write(card1)
        store.write(card2)

        approve_cards = store.query_by_category("APPROVE")
        assert len(approve_cards) == 1
        assert approve_cards[0]["category"] == "APPROVE"

    def test_sha256_chain_immutability(self, store):
        """Test SHA-256 chain is computed and stored."""
        card = MemoryCard(
            card_id="mem001",
            principal="agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Test content",
        )

        store.write(card, chain=True)
        read_card = store.read("mem001")

        assert "_hash" in read_card
        assert len(read_card["_hash"]) == 64  # SHA-256 hex digest

    def test_verify_chain(self, store):
        """Test chain verification."""
        card1 = MemoryCard(
            card_id="mem001",
            principal="agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Card 1",
        )
        card2 = MemoryCard(
            card_id="mem002",
            principal="agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Card 2",
        )

        store.write(card1, chain=True)
        store.write(card2, chain=True)

        # Chain should be valid
        assert store.verify_chain()

    def test_all_cards(self, store):
        """Test retrieving all cards."""
        card1 = MemoryCard(
            card_id="mem001",
            principal="agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Card 1",
        )
        card2 = MemoryCard(
            card_id="mem002",
            principal="agent",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            content="Card 2",
        )

        store.write(card1)
        store.write(card2)

        all_cards = store.all_cards()
        assert len(all_cards) == 2
        assert all_cards[0]["card_id"] == "mem001"
        assert all_cards[1]["card_id"] == "mem002"


class TestDecisionLedgerWithChain:
    """Test DecisionLedger with SHA-256 chain immutability."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def ledger(self, temp_dir):
        """Create DecisionLedger with temp directory."""
        return DecisionLedgerWithChain("test-church", temp_dir)

    def test_append_and_find_by_decision(self, ledger):
        """Test appending and finding entries by decision."""
        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry)

        found = ledger.find_by_decision("dec001")
        assert len(found) == 1
        assert found[0]["entry_id"] == "le001"
        assert found[0]["decision_id"] == "dec001"

    def test_append_with_categorization_tags(self, ledger):
        """Test appending entry with Phase 10.5 categorization tags."""
        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        tags = [
            {"tag": "approve", "timestamp": datetime.utcnow().isoformat(), "confidence": 0.95},
            {"tag": "auto_approved", "timestamp": datetime.utcnow().isoformat(), "confidence": 0.88},
        ]

        ledger.append(entry, categorization_tags=tags)

        found = ledger.find_by_decision("dec001")
        assert len(found[0]["categorization_tags"]) == 2
        assert found[0]["categorization_tags"][0]["tag"] == "approve"

    def test_find_by_category(self, ledger):
        """Test finding entries by category."""
        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.OVERRIDE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry1)
        ledger.append(entry2)

        approves = ledger.find_by_category("approve")
        assert len(approves) == 1
        assert approves[0]["category"] == "approve"

    def test_find_by_category_with_date_range(self, ledger):
        """Test finding entries by category with date filtering."""
        now = datetime.utcnow()
        past = now - timedelta(days=10)

        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=past,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry1)
        ledger.append(entry2)

        # Query for last 5 days
        start = now - timedelta(days=5)
        approves = ledger.find_by_category("approve", period_start=start)
        assert len(approves) == 1
        assert approves[0]["decision_id"] == "dec002"

    def test_find_by_actor(self, ledger):
        """Test finding entries by actor."""
        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry)

        found = ledger.find_by_actor("user1")
        assert len(found) == 1
        assert found[0]["authoring_actor"]["actor_id"] == "user1"

    def test_find_overrides(self, ledger):
        """Test finding override decisions."""
        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.OVERRIDE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry1)
        ledger.append(entry2)

        overrides = ledger.find_overrides()
        assert len(overrides) == 1
        assert overrides[0]["category"] == "override"

    def test_sha256_chain_immutability(self, ledger):
        """Test SHA-256 chain is computed for ledger entries."""
        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry)

        found = ledger.find_by_decision("dec001")
        assert "_hash" in found[0]
        assert len(found[0]["_hash"]) == 64  # SHA-256 hex

    def test_verify_chain(self, ledger):
        """Test ledger chain verification."""
        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry1)
        ledger.append(entry2)

        assert ledger.verify_chain()

    def test_all_entries(self, ledger):
        """Test retrieving all entries."""
        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.APPROVE,
            timestamp=datetime.utcnow(),
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        ledger.append(entry1)
        ledger.append(entry2)

        all_entries = ledger.all_entries()
        assert len(all_entries) == 2


class TestGuiderFeedbackStore:
    """Test Phase 10.6 guider learning from Decision Ledger."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def feedback_store_with_ledger(self, temp_dir):
        """Create GuiderFeedbackStore with its own ledger instance."""
        from backend.cards.ledger import DecisionLedgerWithChain

        # Create a feedback store and inject a new ledger for this test
        store = GuiderFeedbackStore("test-church")
        # Replace its ledger with a fresh one in temp_dir
        store.ledger = DecisionLedgerWithChain("test-church", temp_dir)
        return store

    def test_get_recent_decisions_by_category(self, feedback_store_with_ledger):
        """Test retrieving recent decisions by category."""
        # Add some decisions to the ledger
        now = datetime.utcnow()
        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )

        feedback_store_with_ledger.ledger.append(entry)

        decisions = feedback_store_with_ledger.get_recent_decisions_by_category("approve", lookback_days=7)
        assert len(decisions) == 1

    def test_compute_confidence_score(self, feedback_store_with_ledger):
        """Test confidence score computation from approval rate."""
        now = datetime.utcnow()

        # Add 2 approved and 1 rejected decision
        for i in range(2):
            entry = LedgerEntry(
                entry_id=f"le{i:03d}",
                decision_id=f"dec{i:03d}",
                category=DecisionCategory.APPROVE,
                timestamp=now,
                authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
                outcome=DecisionOutcome.ACCEPTED,
            )
            feedback_store_with_ledger.ledger.append(entry)

        entry = LedgerEntry(
            entry_id="le003",
            decision_id="dec003",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.REJECTED,
        )
        feedback_store_with_ledger.ledger.append(entry)

        confidence = feedback_store_with_ledger.compute_confidence_score("approve")
        # 2 approvals / 3 total = 0.666...
        assert 0.6 < confidence < 0.7

    def test_get_guider_context(self, feedback_store_with_ledger):
        """Test getting contextual info for a guider."""
        now = datetime.utcnow()

        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
        )
        feedback_store_with_ledger.ledger.append(entry)

        context = feedback_store_with_ledger.get_guider_context("approve")
        assert context["category"] == "approve"
        assert context["total_decisions"] == 1
        assert context["approvals"] == 1
        assert "confidence_score" in context

    def test_find_similar_decisions(self, feedback_store_with_ledger):
        """Test finding similar past decisions for reference."""
        now = datetime.utcnow()

        entry1 = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
            metadata={"account": "10000", "vendor": "Vendor A"},
        )
        entry2 = LedgerEntry(
            entry_id="le002",
            decision_id="dec002",
            category=DecisionCategory.APPROVE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
            metadata={"account": "20000", "vendor": "Vendor B"},
        )

        feedback_store_with_ledger.ledger.append(entry1)
        feedback_store_with_ledger.ledger.append(entry2)

        # Find decisions with account = 10000
        similar = feedback_store_with_ledger.find_similar_decisions(
            "approve", {"account": "10000"}
        )
        assert len(similar) == 1
        assert similar[0]["metadata"]["vendor"] == "Vendor A"

    def test_get_override_patterns(self, feedback_store_with_ledger):
        """Test analyzing override patterns."""
        now = datetime.utcnow()

        entry = LedgerEntry(
            entry_id="le001",
            decision_id="dec001",
            category=DecisionCategory.OVERRIDE,
            timestamp=now,
            authoring_actor={"actor_id": "user1", "actor_type": "TREASURER_ADMIN"},
            outcome=DecisionOutcome.ACCEPTED,
            metadata={"original_category": "RECOGNIZE"},
        )

        feedback_store_with_ledger.ledger.append(entry)

        patterns = feedback_store_with_ledger.get_override_patterns()
        assert patterns["total_overrides"] == 1
        assert "override_rates_by_category" in patterns
