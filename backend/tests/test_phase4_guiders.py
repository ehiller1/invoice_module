"""Phase 4 — Per-guider unit tests (approve / block / escalate cases)."""
from __future__ import annotations

from backend.membrane.guiders import (
    AccountingIntegrityGuider,
    PaymentDedupGuider,
    PolityAndDeferenceGuider,
    AbundanceAndStewardshipGuider,
    WitnessAndProvenanceGuider,
    DignityGuider,
)
from backend.membrane.guiders.base import Decision


# ----------------------- accounting-integrity -----------------------

def test_accounting_integrity_approves_valid():
    g = AccountingIntegrityGuider()
    v = g.evaluate({"gl_accounts": ["6010", "1000"], "mapping_confidence": 0.95})
    assert v.decision == Decision.APPROVE
    assert v.guider == "accounting-integrity"


def test_accounting_integrity_blocks_invalid_account():
    g = AccountingIntegrityGuider()
    v = g.evaluate({"gl_accounts": ["??"]})
    assert v.decision == Decision.BLOCK
    assert "invalid" in v.reason.lower()


def test_accounting_integrity_blocks_circular():
    g = AccountingIntegrityGuider()
    v = g.evaluate({"gl_accounts": ["6010"], "circular_allocation": True})
    assert v.decision == Decision.BLOCK


def test_accounting_integrity_escalates_low_confidence():
    g = AccountingIntegrityGuider(min_mapping_confidence=0.7)
    v = g.evaluate({"gl_accounts": ["6010"], "mapping_confidence": 0.3})
    assert v.decision == Decision.ESCALATE


def test_accounting_integrity_custom_validator():
    g = AccountingIntegrityGuider(account_validator=lambda a: a == "6010")
    assert g.evaluate({"gl_accounts": ["6010"]}).decision == Decision.APPROVE
    assert g.evaluate({"gl_accounts": ["9999"]}).decision == Decision.BLOCK


# ----------------------- payment-dedup -----------------------

def test_payment_dedup_approves_clean():
    g = PaymentDedupGuider()
    v = g.evaluate({"vendor": "ACME", "amount": 100.0})
    assert v.decision == Decision.APPROVE


def test_payment_dedup_blocks_signal_hard():
    g = PaymentDedupGuider()
    v = g.evaluate({"signal_name": "PAYMENT_DEDUP_RISK", "payload": {"amount": 100}})
    assert v.decision == Decision.BLOCK


def test_payment_dedup_blocks_exact_duplicate():
    g = PaymentDedupGuider()
    v = g.evaluate({"is_exact_duplicate": True, "vendor": "ACME", "amount": 100})
    assert v.decision == Decision.BLOCK


def test_payment_dedup_escalates_history_match():
    history = lambda v, a: [{"days_ago": 2}]
    g = PaymentDedupGuider(history_lookup=history, window_days=7)
    v = g.evaluate({"vendor": "ACME", "amount": 100.0})
    assert v.decision == Decision.ESCALATE
    assert v.metadata["prior_count"] == 1


def test_payment_dedup_outside_window_approves():
    history = lambda v, a: [{"days_ago": 30}]
    g = PaymentDedupGuider(history_lookup=history, window_days=7)
    v = g.evaluate({"vendor": "ACME", "amount": 100.0})
    assert v.decision == Decision.APPROVE


# ----------------------- polity-and-deference -----------------------

def test_polity_approves_within_band():
    g = PolityAndDeferenceGuider()
    v = g.evaluate({"principal_roles": ["FINANCE_STAFF"], "amount": 1000})
    assert v.decision == Decision.APPROVE


def test_polity_blocks_no_roles():
    g = PolityAndDeferenceGuider()
    v = g.evaluate({"amount": 100})
    assert v.decision == Decision.BLOCK


def test_polity_override_allowed_over_band():
    g = PolityAndDeferenceGuider()
    v = g.evaluate({"principal_roles": ["FINANCE_STAFF"], "amount": 50_000})
    assert v.decision == Decision.OVERRIDE_ALLOWED
    assert "TREASURER" in v.override_allowed_by
    assert "ADMIN" in v.override_allowed_by


def test_polity_escalates_with_chain_resolver():
    chain = lambda amt, roles: ["FINANCE_MANAGER", "TREASURER"]
    g = PolityAndDeferenceGuider(chain_resolver=chain)
    v = g.evaluate({"principal_roles": ["FINANCE_STAFF"], "amount": 50_000})
    assert v.decision == Decision.ESCALATE
    assert v.metadata["approval_chain"][0] == "FINANCE_MANAGER"


def test_polity_treasurer_unlimited():
    g = PolityAndDeferenceGuider()
    v = g.evaluate({"principal_roles": ["TREASURER"], "amount": 10_000_000})
    assert v.decision == Decision.APPROVE


# ----------------------- abundance-and-stewardship -----------------------

def test_abundance_approves_under_budget():
    g = AbundanceAndStewardshipGuider()
    v = g.evaluate({
        "category": "office",
        "amount": 100,
        "budget_info": {"budget": 1000, "spent": 100},
    })
    assert v.decision == Decision.APPROVE


def test_abundance_blocks_fund_restriction_signal():
    g = AbundanceAndStewardshipGuider()
    v = g.evaluate({"signal_name": "FUND_RESTRICTION_VIOLATION", "payload": {}})
    assert v.decision == Decision.BLOCK


def test_abundance_blocks_fund_restriction_flag():
    g = AbundanceAndStewardshipGuider()
    v = g.evaluate({"fund_restriction_violation": True, "fund": "BUILDING_FUND"})
    assert v.decision == Decision.BLOCK


def test_abundance_escalates_high_utilization():
    g = AbundanceAndStewardshipGuider(utilization_warn=0.8, variance_block=1.2)
    v = g.evaluate({
        "category": "office",
        "amount": 100,
        "budget_info": {"budget": 1000, "spent": 800},
    })
    assert v.decision == Decision.ESCALATE


def test_abundance_blocks_over_variance():
    g = AbundanceAndStewardshipGuider(utilization_warn=0.8, variance_block=1.2)
    v = g.evaluate({
        "category": "office",
        "amount": 500,
        "budget_info": {"budget": 1000, "spent": 800},
    })
    assert v.decision == Decision.BLOCK


# ----------------------- witness-and-provenance -----------------------

def test_witness_approves_low_risk():
    g = WitnessAndProvenanceGuider()
    v = g.evaluate({"principal": "alice", "risk_score": 0.1})
    assert v.decision == Decision.APPROVE


def test_witness_escalates_missing_principal():
    g = WitnessAndProvenanceGuider()
    v = g.evaluate({"risk_score": 0.1})
    assert v.decision == Decision.ESCALATE


def test_witness_blocks_high_risk_no_explanation():
    g = WitnessAndProvenanceGuider(high_risk_threshold=0.7)
    v = g.evaluate({"principal": "alice", "risk_score": 0.9})
    assert v.decision == Decision.BLOCK


def test_witness_escalates_high_risk_with_explanation():
    g = WitnessAndProvenanceGuider(high_risk_threshold=0.7)
    v = g.evaluate({
        "principal": "alice",
        "risk_score": 0.9,
        "explanation": "vendor verified by CFO",
    })
    assert v.decision == Decision.ESCALATE


def test_witness_records_to_ledger():
    captured = []
    g = WitnessAndProvenanceGuider(ledger_recorder=lambda rec: captured.append(rec))
    g.evaluate({"principal": "alice", "risk_score": 0.1})
    assert len(captured) == 1
    assert captured[0]["principal"] == "alice"


# ----------------------- dignity -----------------------

def test_dignity_approves_default():
    g = DignityGuider()
    v = g.evaluate({"amount": 500})
    assert v.decision == Decision.APPROVE


def test_dignity_blocks_po_without_quotes():
    g = DignityGuider()
    v = g.evaluate({"type": "purchase_order", "amount": 25_000, "quote_count": 1})
    assert v.decision == Decision.BLOCK


def test_dignity_approves_po_with_quotes():
    g = DignityGuider()
    v = g.evaluate({"type": "purchase_order", "amount": 25_000, "quotes": ["a", "b", "c"]})
    assert v.decision == Decision.APPROVE


def test_dignity_escalates_po_exception_approved():
    g = DignityGuider()
    v = g.evaluate({
        "type": "purchase_order",
        "amount": 25_000,
        "quote_count": 1,
        "exception_approved": True,
    })
    assert v.decision == Decision.ESCALATE


def test_dignity_blocks_on_policy_signal():
    g = DignityGuider()
    v = g.evaluate({"signal_name": "POLICY_VIOLATION", "payload": {"policy_id": "P-77"}})
    assert v.decision == Decision.BLOCK


def test_dignity_policy_evaluator_block():
    eval_fn = lambda payload: [{"id": "P-1", "violated": True, "severity": "block", "reason": "x"}]
    g = DignityGuider(policy_evaluator=eval_fn)
    v = g.evaluate({"amount": 100})
    assert v.decision == Decision.BLOCK


def test_dignity_policy_evaluator_escalate():
    eval_fn = lambda payload: [{"id": "P-2", "violated": True, "severity": "escalate", "reason": "x"}]
    g = DignityGuider(policy_evaluator=eval_fn)
    v = g.evaluate({"amount": 100})
    assert v.decision == Decision.ESCALATE
