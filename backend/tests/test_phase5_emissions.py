"""Phase 5 emission tests — verify 10 emitters at pipeline points.

Tests use a MockPublisher (capturing publish calls) and toggle the
EMBARK_MEMBRANE_PHASE_5 feature flag.
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockPublisher:
    """Captures publish_signal calls. Async-safe."""

    def __init__(self) -> None:
        self.signals: List[Any] = []

    async def publish_signal(self, signal: Any) -> str:
        self.signals.append(signal)
        return "msg-id-mock"


@pytest.fixture
def phase5_on(monkeypatch):
    monkeypatch.setenv("EMBARK_MEMBRANE_PHASE_5", "1")
    # Reload feature_flags module so module-level constants pick up env.
    from backend.membrane import feature_flags
    importlib.reload(feature_flags)
    from backend.membrane.emitters import invoice_emitters
    importlib.reload(invoice_emitters)
    yield
    monkeypatch.delenv("EMBARK_MEMBRANE_PHASE_5", raising=False)
    importlib.reload(feature_flags)
    importlib.reload(invoice_emitters)


@pytest.fixture
def phase5_off(monkeypatch):
    monkeypatch.delenv("EMBARK_MEMBRANE_PHASE_5", raising=False)
    from backend.membrane import feature_flags
    importlib.reload(feature_flags)
    from backend.membrane.emitters import invoice_emitters
    importlib.reload(invoice_emitters)
    yield


# ---------------------------------------------------------------------------
# Feature flag gating
# ---------------------------------------------------------------------------

def test_emitter_noop_when_flag_off(phase5_off):
    from backend.membrane.emitters import invoice_emitters
    pub = MockPublisher()
    result = invoice_emitters.emit_invoice_ingested(
        filename="x.pdf", vendor="V", total_amount="100", publisher=pub
    )
    assert result is None
    assert pub.signals == []


def test_emitter_emits_when_flag_on(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    pub = MockPublisher()
    sig = invoice_emitters.emit_invoice_ingested(
        filename="x.pdf", vendor="V", total_amount="100", publisher=pub
    )
    assert sig is not None
    assert sig.signal_name == "INVOICE_INGESTED"
    assert sig.signal_id == 59


# ---------------------------------------------------------------------------
# 10 emitters — payload + envelope checks
# ---------------------------------------------------------------------------

def test_emit_invoice_ingested_payload(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_invoice_ingested(
        filename="inv.pdf", vendor="Acme", total_amount="500.00", job_id="job-1"
    )
    assert sig.payload["filename"] == "inv.pdf"
    assert sig.payload["vendor"] == "Acme"
    assert sig.payload["total_amount"] == "500.00"
    assert sig.target_channel == "impact:proposed:invoice_ingested"


def test_emit_mapping_confidence_low(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_mapping_confidence_low(
        account="6100", confidence=0.42, suggestion="6105", job_id="j"
    )
    assert sig.signal_id == 60
    assert sig.payload["account"] == "6100"
    assert sig.payload["confidence"] == 0.42


def test_emit_budget_overage_risk(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_budget_overage_risk(
        account="6100", amount="2000", projected_balance="12000"
    )
    assert sig.signal_id == 61
    assert sig.payload["projected_balance"] == "12000"


def test_emit_fund_restriction_violation_hardblock(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_fund_restriction_violation(
        fund="missions", restriction_type="donor_restricted",
        violation_detail="cannot reallocate"
    )
    assert sig.signal_id == 62
    assert sig.payload["hard_block"] is True


def test_emit_journal_entry_ready_p0_sensitive(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_journal_entry_ready(
        je_id="je-1", account_entries=[{"a": "6100"}], amounts=["100"]
    )
    assert sig.signal_id == 63
    assert sig.privacy_class == "P0"
    assert sig.payload["sensitive"] is True


def test_emit_payment_dedup_risk_hardblock(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_payment_dedup_risk(
        payment_id="p2", prior_payment_id="p1"
    )
    assert sig.signal_id == 64
    assert sig.payload["hard_block"] is True


def test_emit_reconciliation_exception(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_reconciliation_exception(
        txn_id="t1", amount="42.00", days_unmatched=7
    )
    assert sig.signal_id == 65
    assert sig.crosses_membrane is True
    assert sig.payload["days_unmatched"] == 7


def test_emit_approval_deadline_pressure(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_approval_deadline_pressure(
        queue_length=5, oldest_item_age_days=3.5, window_label="15:00"
    )
    assert sig.signal_id == 66
    assert sig.payload["queue_length"] == 5


def test_emit_hitl_escalation(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_hitl_escalation(
        item_id="exc-1", escalation_reason="manual review", escalated_by="user@x"
    )
    assert sig.signal_id == 67
    assert sig.payload["escalated_by"] == "user@x"


def test_emit_policy_violation(phase5_on):
    from backend.membrane.emitters import invoice_emitters
    sig = invoice_emitters.emit_policy_violation(
        policy_id="pol-1", rule_violated="dual_signature_required",
        entity_affected="je-99"
    )
    assert sig.signal_id == 68
    assert sig.payload["rule_violated"] == "dual_signature_required"


# ---------------------------------------------------------------------------
# Publisher integration
# ---------------------------------------------------------------------------

def test_publisher_receives_signal_when_flag_on(phase5_on):
    import asyncio
    from backend.membrane.emitters import invoice_emitters

    pub = MockPublisher()

    async def runner():
        invoice_emitters.emit_invoice_ingested(
            filename="x.pdf", vendor="V", total_amount="1", publisher=pub
        )
        # allow fire-and-forget tasks to run
        await asyncio.sleep(0)

    asyncio.run(runner())
    assert len(pub.signals) == 1
    assert pub.signals[0].signal_name == "INVOICE_INGESTED"


def test_emitter_never_raises_on_publisher_failure(phase5_on):
    from backend.membrane.emitters import invoice_emitters

    class BadPub:
        async def publish_signal(self, s):
            raise RuntimeError("boom")

    # Should not raise.
    sig = invoice_emitters.emit_invoice_ingested(
        filename="x.pdf", vendor="V", total_amount="1", publisher=BadPub()
    )
    assert sig is not None  # build still succeeds
