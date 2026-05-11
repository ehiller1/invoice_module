"""Phase 9: Reconciliation + Payment Dedup Integration (18 tests)."""

import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from backend.membrane.reconciliation.dedup_integration import PaymentDedupIntegration
from backend.membrane.reconciliation.recon_integration import ReconciliationIntegration
from backend.membrane.guiders.base import Decision
from backend.tools.payment_dedup_store import PaymentDedupStore
from backend.tools.recon_exception_store import ReconExceptionStore


class TestPaymentDedupStore:
    """Test PaymentDedupStore class."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_record_payment(self, temp_dir):
        """Test recording a payment."""
        store = PaymentDedupStore(data_dir=temp_dir)

        store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("1000.00"),
            payment_date=datetime.utcnow(),
            reference_id="REF001",
        )

        history = store.get_payment_history("test-church", vendor="Vendor A")
        assert len(history) == 1
        assert history[0]["vendor"] == "Vendor A"
        assert history[0]["amount"] == "1000.00"

    def test_is_exact_duplicate(self, temp_dir):
        """Test exact duplicate detection."""
        store = PaymentDedupStore(data_dir=temp_dir)
        now = datetime.utcnow()

        # Record first payment
        store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("500.00"),
            payment_date=now - timedelta(hours=2),
            reference_id="REF001",
        )

        # Check if recent same payment is duplicate
        is_dup = store.is_exact_duplicate(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("500.00"),
            payment_date=now,
        )
        assert is_dup

    def test_is_not_exact_duplicate_different_vendor(self, temp_dir):
        """Test non-duplicate detection (different vendor)."""
        store = PaymentDedupStore(data_dir=temp_dir)
        now = datetime.utcnow()

        store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("500.00"),
            payment_date=now - timedelta(hours=2),
            reference_id="REF001",
        )

        is_dup = store.is_exact_duplicate(
            church_id="test-church",
            vendor="Vendor B",
            amount=Decimal("500.00"),
            payment_date=now,
        )
        assert not is_dup

    def test_find_probable_duplicates(self, temp_dir):
        """Test probable duplicate detection."""
        store = PaymentDedupStore(data_dir=temp_dir)
        now = datetime.utcnow()

        # Record first payment
        store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("750.00"),
            payment_date=now - timedelta(days=2),
            reference_id="REF001",
        )

        # Find probable duplicates
        dups = store.find_probable_duplicates(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("750.00"),
            days_lookback=7,
        )
        assert len(dups) == 1

    def test_get_payment_history_filtered(self, temp_dir):
        """Test payment history filtering."""
        store = PaymentDedupStore(data_dir=temp_dir)
        now = datetime.utcnow()

        # Record multiple payments
        store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("100.00"),
            payment_date=now,
            reference_id="REF001",
        )

        store.record_payment(
            church_id="test-church",
            vendor="Vendor B",
            amount=Decimal("200.00"),
            payment_date=now,
            reference_id="REF002",
        )

        # Filter by vendor
        history = store.get_payment_history(
            "test-church",
            vendor="Vendor A",
        )
        assert len(history) == 1
        assert history[0]["vendor"] == "Vendor A"


class TestReconExceptionStore:
    """Test ReconExceptionStore class."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_record_exception(self, temp_dir):
        """Test recording an exception."""
        store = ReconExceptionStore(data_dir=temp_dir)

        exc_id = store.record_exception(
            church_id="test-church",
            exception_type="BANK_ONLY",
            txn_id="TXN001",
            amount="500.00",
            description="Unmatched bank deposit",
        )

        assert exc_id is not None
        exceptions = store.get_exceptions("test-church")
        assert len(exceptions) == 1
        assert exceptions[0]["txn_id"] == "TXN001"

    def test_get_unresolved_exceptions(self, temp_dir):
        """Test getting unresolved exceptions."""
        store = ReconExceptionStore(data_dir=temp_dir)

        exc_id = store.record_exception(
            church_id="test-church",
            exception_type="ACS_ONLY",
            txn_id="TXN002",
            amount="750.00",
            description="ACS entry with no bank match",
        )

        unresolved = store.get_unresolved_exceptions("test-church")
        assert len(unresolved) == 1

    def test_resolve_exception(self, temp_dir):
        """Test resolving an exception."""
        store = ReconExceptionStore(data_dir=temp_dir)

        exc_id = store.record_exception(
            church_id="test-church",
            exception_type="AMOUNT_MISMATCH",
            txn_id="TXN003",
            amount="1000.00",
            description="Amount mismatch",
        )

        success = store.resolve_exception(
            church_id="test-church",
            exception_id=exc_id,
            resolution_notes="Corrected data entry error",
        )
        assert success

        unresolved = store.get_unresolved_exceptions("test-church")
        assert len(unresolved) == 0

    def test_get_exception_summary(self, temp_dir):
        """Test exception summary."""
        store = ReconExceptionStore(data_dir=temp_dir)

        store.record_exception(
            church_id="test-church",
            exception_type="BANK_ONLY",
            txn_id="TXN001",
            amount="100.00",
            description="Test",
            days_unmatched=5,
        )

        store.record_exception(
            church_id="test-church",
            exception_type="ACS_ONLY",
            txn_id="TXN002",
            amount="200.00",
            description="Test",
            days_unmatched=3,
        )

        summary = store.get_exception_summary("test-church")
        assert summary["total_exceptions"] == 2
        assert summary["unresolved_count"] == 2
        assert "BANK_ONLY" in summary["by_type"]
        assert "ACS_ONLY" in summary["by_type"]


class TestPaymentDedupIntegration:
    """Test PaymentDedupIntegration class."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def integration(self, temp_dir):
        """Create integration with temp store."""
        integration = PaymentDedupIntegration()
        integration.store = PaymentDedupStore(data_dir=temp_dir)
        return integration

    def test_check_for_exact_duplicate(self, integration):
        """Test exact duplicate check."""
        now = datetime.utcnow()

        # Record first payment
        integration.store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("1000.00"),
            payment_date=now - timedelta(hours=1),
            reference_id="REF001",
        )

        # Check for duplicate
        decision, reason = integration.check_for_duplicate(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("1000.00"),
            payment_date=now,
            reference_id="REF002",
        )

        assert decision == Decision.BLOCK
        assert "Exact duplicate" in reason

    def test_check_for_probable_duplicate(self, integration):
        """Test probable duplicate check."""
        now = datetime.utcnow()

        # Record first payment
        integration.store.record_payment(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("500.00"),
            payment_date=now - timedelta(days=3),
            reference_id="REF001",
        )

        # Check for probable duplicate
        decision, reason = integration.check_for_duplicate(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("500.00"),
            payment_date=now,
            reference_id="REF002",
        )

        assert decision == Decision.ESCALATE
        assert "Probable duplicate" in reason

    def test_check_no_duplicate(self, integration):
        """Test no duplicate found."""
        now = datetime.utcnow()

        decision, reason = integration.check_for_duplicate(
            church_id="test-church",
            vendor="New Vendor",
            amount=Decimal("999.99"),
            payment_date=now,
            reference_id="REF001",
        )

        assert decision is None
        assert reason is None

    def test_record_payment_approved(self, integration):
        """Test recording approved payment."""
        now = datetime.utcnow()

        integration.record_payment_approved(
            church_id="test-church",
            vendor="Vendor A",
            amount=Decimal("1000.00"),
            payment_date=now,
            reference_id="REF001",
            payment_method="CHECK",
        )

        history = integration.get_payment_history("test-church", vendor="Vendor A")
        assert len(history) == 1
        assert history[0]["payment_method"] == "CHECK"


class TestReconciliationIntegration:
    """Test ReconciliationIntegration class."""

    @pytest.fixture
    def temp_dir(self):
        """Temp directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def integration(self, temp_dir):
        """Create integration with temp store."""
        integration = ReconciliationIntegration()
        integration.store = ReconExceptionStore(data_dir=temp_dir)
        return integration

    def test_record_unmatched_transaction(self, integration):
        """Test recording unmatched transaction."""
        exception_id = integration.record_unmatched_transaction(
            church_id="test-church",
            txn_id="TXN001",
            amount="500.00",
            description="Bank deposit not in ACS",
            exception_type="BANK_ONLY",
        )

        assert exception_id is not None
        exceptions = integration.get_exceptions("test-church")
        assert len(exceptions) == 1

    def test_check_reconciliation_status_clean(self, integration):
        """Test reconciliation status when clean."""
        decision, reason = integration.check_reconciliation_status("test-church")
        assert decision is None
        assert reason is None

    def test_check_reconciliation_status_unresolved(self, integration):
        """Test reconciliation status with unresolved exceptions."""
        integration.record_unmatched_transaction(
            church_id="test-church",
            txn_id="TXN001",
            amount="100.00",
            description="Test",
            days_unmatched=5,
        )

        decision, reason = integration.check_reconciliation_status("test-church")
        assert decision == Decision.ESCALATE
        assert "Unresolved" in reason

    def test_resolve_exception(self, integration):
        """Test resolving exception."""
        exc_id = integration.record_unmatched_transaction(
            church_id="test-church",
            txn_id="TXN001",
            amount="500.00",
            description="Test",
        )

        success = integration.resolve_exception(
            church_id="test-church",
            exception_id=exc_id,
            resolution_notes="Matched to JE12345",
        )
        assert success

    def test_get_exception_summary(self, integration):
        """Test getting exception summary."""
        integration.record_unmatched_transaction(
            church_id="test-church",
            txn_id="TXN001",
            amount="100.00",
            description="BANK_ONLY",
            exception_type="BANK_ONLY",
        )

        integration.record_unmatched_transaction(
            church_id="test-church",
            txn_id="TXN002",
            amount="200.00",
            description="ACS_ONLY",
            exception_type="ACS_ONLY",
        )

        summary = integration.get_exception_summary("test-church")
        assert summary["total_exceptions"] == 2
        assert summary["unresolved_count"] == 2
