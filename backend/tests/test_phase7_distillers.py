"""Phase 7 distiller tests — verify each distiller extracts public-facing
fields only and never leaks P3/sensitive data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.membrane.envelope import ImpactSignal
from backend.membrane.perturbations import get_perturbation
from backend.membrane.distiller.invoice_distiller import InvoiceDistiller
from backend.membrane.distiller.payment_distiller import PaymentDistiller
from backend.membrane.distiller.recon_distiller import ReconDistiller
from backend.membrane.distiller.policy_distiller import PolicyDistiller
from backend.membrane.distiller.hitl_distiller import HITLDistiller


def _signal(name: str, payload: dict) -> ImpactSignal:
    p = get_perturbation(name)
    return ImpactSignal(
        envelope_version="1",
        signal_id=p.id,
        signal_name=p.name,
        event_id=str(uuid.uuid4()),
        occurred_at=datetime.now(tz=timezone.utc),
        privacy_class=p.privacy_class,  # type: ignore[arg-type]
        crosses_membrane=p.crosses_membrane,
        target_channel=p.target_channel,
        payload=payload,
        source="test",
        retention=p.default_retention,
    )


# ---------------------------------------------------------------------------
# InvoiceDistiller
# ---------------------------------------------------------------------------

def test_invoice_distiller_handles_invoice_ingested():
    sig = _signal("INVOICE_INGESTED", {
        "signal_id": "abc",
        "filename": "vendor_inv.pdf",
        "vendor": "ACME",
        "total_amount": "1234.56",
        "job_id": "job-1",
        "ssn": "111-22-3333",  # P3 sensitive — must NOT pass through
    })
    out = InvoiceDistiller().distill(sig, context={})
    assert "filename" in out
    assert "vendor" in out
    assert "ssn" not in out
    # No P3 field leaks
    assert out.get("signal_name") == "INVOICE_INGESTED"


def test_invoice_distiller_handles_mapping_confidence_low():
    sig = _signal("MAPPING_CONFIDENCE_LOW", {
        "account": "6100",
        "confidence": 0.42,
        "suggestion": "6200",
        "job_id": "j1",
    })
    out = InvoiceDistiller().distill(sig, context={})
    assert out["account"] == "6100"
    assert out["confidence"] == pytest.approx(0.42)


def test_invoice_distiller_handles_budget_overage_risk():
    sig = _signal("BUDGET_OVERAGE_RISK", {
        "account": "6100",
        "amount": "500.00",
        "projected_balance": "1500.00",
        "job_id": "j1",
    })
    out = InvoiceDistiller().distill(sig, context={})
    assert out["account"] == "6100"
    assert "amount" in out


def test_invoice_distiller_handles_missing_payload():
    sig = _signal("INVOICE_INGESTED", {"signal_id": "x", "filename": "f.pdf"})
    out = InvoiceDistiller().distill(sig, context={})
    assert out["filename"] == "f.pdf"
    assert out.get("vendor") is None


def test_invoice_distiller_journal_entry_marks_sensitive():
    sig = _signal("JOURNAL_ENTRY_READY", {
        "je_id": "JE-1",
        "account_entries": [{"acct": "6100", "amt": "100"}],
        "amounts": {"total": "100"},
        "job_id": "j1",
        "sensitive": True,
    })
    out = InvoiceDistiller().distill(sig, context={})
    # P0 sensitive payload — amounts must be redacted/omitted at distill time
    assert out["je_id"] == "JE-1"
    assert "amounts" not in out or out.get("amounts_redacted") is True


# ---------------------------------------------------------------------------
# PaymentDistiller
# ---------------------------------------------------------------------------

def test_payment_distiller_payment_dedup_risk():
    sig = _signal("PAYMENT_DEDUP_RISK", {
        "payment_id": "PMT-1",
        "prior_payment_id": "PMT-0",
        "hard_block": True,
        "job_id": "j1",
    })
    out = PaymentDistiller().distill(sig, context={})
    assert out["payment_id"] == "PMT-1"
    assert out["prior_payment_id"] == "PMT-0"
    assert out["hard_block"] is True


def test_payment_distiller_drops_unknown_fields():
    sig = _signal("PAYMENT_DEDUP_RISK", {
        "payment_id": "PMT-1",
        "prior_payment_id": "PMT-0",
        "bank_account_number": "9999",  # sensitive
    })
    out = PaymentDistiller().distill(sig, context={})
    assert "bank_account_number" not in out


# ---------------------------------------------------------------------------
# ReconDistiller
# ---------------------------------------------------------------------------

def test_recon_distiller_reconciliation_exception():
    sig = _signal("RECONCILIATION_EXCEPTION", {
        "txn_id": "T1",
        "amount": "12.34",
        "days_unmatched": 7,
    })
    out = ReconDistiller().distill(sig, context={})
    assert out["txn_id"] == "T1"
    assert out["days_unmatched"] == 7


# ---------------------------------------------------------------------------
# PolicyDistiller
# ---------------------------------------------------------------------------

def test_policy_distiller_policy_violation():
    sig = _signal("POLICY_VIOLATION", {
        "policy_id": "P1",
        "rule_violated": "no_self_approval",
        "entity_affected": "user-123",
    })
    out = PolicyDistiller().distill(sig, context={})
    assert out["policy_id"] == "P1"
    assert out["rule_violated"] == "no_self_approval"


def test_policy_distiller_fund_restriction_violation():
    sig = _signal("FUND_RESTRICTION_VIOLATION", {
        "fund": "Missions",
        "restriction_type": "purpose",
        "violation_detail": "non-allowed category",
        "hard_block": True,
    })
    out = PolicyDistiller().distill(sig, context={})
    assert out["fund"] == "Missions"
    assert out["hard_block"] is True


# ---------------------------------------------------------------------------
# HITLDistiller
# ---------------------------------------------------------------------------

def test_hitl_distiller_escalation():
    sig = _signal("HITL_ESCALATION", {
        "item_id": "ITM-1",
        "escalation_reason": "low_confidence",
        "escalated_by": "agent",
    })
    out = HITLDistiller().distill(sig, context={})
    assert out["item_id"] == "ITM-1"
    assert out["escalation_reason"] == "low_confidence"


def test_hitl_distiller_strips_unknown_p3():
    sig = _signal("HITL_ESCALATION", {
        "item_id": "ITM-1",
        "escalation_reason": "x",
        "escalated_by": "agent",
        "reviewer_personal_email": "user@personal.com",  # P3
    })
    out = HITLDistiller().distill(sig, context={})
    assert "reviewer_personal_email" not in out
