"""Phase 4 — Cascade orchestration tests."""
from __future__ import annotations

from backend.membrane.guiders import (
    AccountingIntegrityGuider,
    PaymentDedupGuider,
    PolityAndDeferenceGuider,
    AbundanceAndStewardshipGuider,
    WitnessAndProvenanceGuider,
    DignityGuider,
    GuiderCascade,
    GuiderRegistry,
)
from backend.membrane.guiders.base import Decision, Guider, Verdict
from backend.membrane.guiders.cascade import CASCADE_ORDER


def _ok_payload():
    return {
        "principal": "alice",
        "principal_roles": ["FINANCE_STAFF"],
        "amount": 100,
        "gl_accounts": ["6010"],
        "mapping_confidence": 0.95,
        "vendor": "ACME",
        "risk_score": 0.1,
    }


def test_cascade_default_order():
    c = GuiderCascade()
    assert c.order == list(CASCADE_ORDER)


def test_cascade_all_approve():
    c = GuiderCascade()
    result = c.evaluate(_ok_payload())
    assert result.final_decision == Decision.APPROVE
    assert result.approved
    assert result.halted_on is None
    assert len(result.verdicts) == 6


def test_cascade_stops_at_first_block():
    # Inject an invalid GL account -> accounting-integrity blocks first
    payload = _ok_payload()
    payload["gl_accounts"] = ["??"]
    c = GuiderCascade()
    result = c.evaluate(payload)
    assert result.blocked
    assert result.halted_on == "accounting-integrity"
    # Cascade halted after first guider
    assert len(result.verdicts) == 1
    assert result.verdicts[0].decision == Decision.BLOCK


def test_cascade_block_in_middle_halts():
    # Payment dedup hard-blocks via signal name; earlier guider approves
    payload = _ok_payload()
    perturbation = {"signal_name": "PAYMENT_DEDUP_RISK", "payload": payload}
    c = GuiderCascade()
    result = c.evaluate(perturbation)
    assert result.blocked
    assert result.halted_on == "payment-dedup"
    # accounting-integrity ran (approve) + payment-dedup (block) = 2 verdicts
    assert len(result.verdicts) == 2


def test_cascade_collects_escalations_when_no_block():
    # Low mapping confidence -> escalate; rest approve
    payload = _ok_payload()
    payload["mapping_confidence"] = 0.2
    c = GuiderCascade()
    result = c.evaluate(payload)
    assert result.final_decision == Decision.ESCALATE
    assert len(result.verdicts) == 6
    escalations = [v for v in result.verdicts if v.decision == Decision.ESCALATE]
    assert any(v.guider == "accounting-integrity" for v in escalations)


def test_cascade_override_allowed_aggregates():
    payload = _ok_payload()
    payload["amount"] = 100_000  # over band -> polity OVERRIDE_ALLOWED
    c = GuiderCascade()
    result = c.evaluate(payload)
    # No hard block expected here
    assert not result.blocked
    assert result.final_decision == Decision.OVERRIDE_ALLOWED
    assert "TREASURER" in result.overrides_required()
    assert result.can_be_overridden_by(["TREASURER"])
    assert not result.can_be_overridden_by(["FINANCE_STAFF"])


def test_cascade_emits_to_sink():
    received = []
    c = GuiderCascade(sink=lambda channel, payload: received.append((channel, payload)))
    c.evaluate(_ok_payload())
    assert len(received) == 1
    channel, body = received[0]
    assert channel == "impact:resolved:cascade_verdict"
    assert body["final_decision"] == "APPROVE"
    assert len(body["verdicts"]) == 6


def test_cascade_records_to_ledger():
    records = []
    c = GuiderCascade(ledger=lambda rec: records.append(rec))
    c.evaluate({"signal_name": "INVOICE_INGESTED", "payload": _ok_payload()})
    assert len(records) == 1
    assert records[0]["perturbation"] == "INVOICE_INGESTED"


def test_cascade_sink_failure_does_not_break():
    def bad_sink(ch, body):
        raise RuntimeError("boom")
    c = GuiderCascade(sink=bad_sink)
    # Should not raise
    result = c.evaluate(_ok_payload())
    assert result.approved


def test_cascade_custom_guiders():
    class AlwaysApprove(Guider):
        name = "always-approve"

        def evaluate(self, perturbation):
            return Verdict(self.name, Decision.APPROVE, 1.0, "ok")

    c = GuiderCascade(guiders=[AlwaysApprove(), AlwaysApprove()])
    result = c.evaluate({})
    assert result.approved
    assert len(result.verdicts) == 2


def test_registry_discovers_all_six():
    reg = GuiderRegistry()
    assert set(reg.names()) == {
        "accounting-integrity",
        "payment-dedup",
        "polity-and-deference",
        "abundance-and-stewardship",
        "witness-and-provenance",
        "dignity",
    }


def test_registry_returns_singleton_per_name():
    reg = GuiderRegistry()
    a = reg.get("dignity")
    b = reg.get("dignity")
    assert a is b


def test_registry_all_returns_six_instances():
    reg = GuiderRegistry()
    guiders = reg.all()
    assert len(guiders) == 6
    assert all(isinstance(g, Guider) for g in guiders)


def test_registry_register_override():
    class Stub(Guider):
        name = "dignity"
        def evaluate(self, p):
            return Verdict(self.name, Decision.APPROVE, 1.0, "stub")

    reg = GuiderRegistry()
    reg.register("dignity", Stub())
    assert reg.get("dignity").evaluate({}).reason == "stub"


def test_registry_learning_state_stub():
    reg = GuiderRegistry()
    reg.update_learning_state("dignity", calls=3)
    assert reg.get_learning_state("dignity") == {"calls": 3}
