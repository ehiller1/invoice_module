"""Shared pytest fixtures.

Phase 2: install LocalTransport + LocalEventQuery singletons so any test
that touches the membrane transport layer gets a clean in-process backend.

Phase 4: Add test data factories for generating common test objects.
"""
from __future__ import annotations

import pytest

from backend.membrane.event_query import (
    LocalEventQuery,
    init_query_transport,
    reset_query_transport_for_tests,
)
from backend.membrane.transport import (
    LocalTransport,
    init_transport,
    reset_transport_for_tests,
)
from backend.models.schemas import JEStatus, PaymentMethod
from backend.tests.factories import (
    AccountingContextFactory,
    BudgetPlanFactory,
    JournalEntryFactory,
    VendorFactory,
)


@pytest.fixture
def local_transport() -> LocalTransport:
    reset_transport_for_tests()
    return init_transport(LocalTransport())  # type: ignore[return-value]


@pytest.fixture
def local_event_query() -> LocalEventQuery:
    reset_query_transport_for_tests()
    return init_query_transport(LocalEventQuery())  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _reset_membrane_singletons():
    reset_transport_for_tests()
    reset_query_transport_for_tests()
    yield
    reset_transport_for_tests()
    reset_query_transport_for_tests()


# ---------------------------------------------------------------------------
# Test Data Factories - Phase 4
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_je():
    """A minimal sample journal entry for testing."""
    return JournalEntryFactory.build()


@pytest.fixture
def sample_je_approved():
    """An approved journal entry."""
    return JournalEntryFactory.build(status=JEStatus.APPROVED)


@pytest.fixture
def sample_vendor():
    """A sample vendor with ACH payment method."""
    return VendorFactory.build()


@pytest.fixture
def sample_vendor_check_only():
    """A sample vendor accepting checks only."""
    return VendorFactory.build(
        payment_methods=[PaymentMethod.CHECK],
        preferred_method=PaymentMethod.CHECK,
        check_payee_name="Check Payee Name",
    )


@pytest.fixture
def sample_budget_plan():
    """A sample budget plan with default accounts."""
    return BudgetPlanFactory.build()


@pytest.fixture
def sample_accounting_context():
    """A minimal accounting context for testing."""
    return AccountingContextFactory.build()
