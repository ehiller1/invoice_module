"""Phase 7 orchestrator tests — full pipeline E2E."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from backend.membrane.envelope import ImpactSignal
from backend.membrane.perturbations import get_perturbation
from backend.membrane.guiders.base import Decision, Verdict, Guider
from backend.membrane.guiders.cascade import GuiderCascade, CascadeResult
from backend.membrane.orchestrator import MembraneOrchestrator, OrchestrationResult
from backend.membrane.redactor import Redactor, Role


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class MockPublisher:
    def __init__(self) -> None:
        self.calls: List[tuple] = []

    async def publish(self, channel: str, payload: Dict[str, Any]) -> str:
        self.calls.append((channel, payload))
        return f"msg-{len(self.calls)}"

    async def publish_signal(self, signal: Any) -> str:
        return await self.publish(signal.target_channel, signal.model_dump(mode="json"))


class StaticGuider(Guider):
    def __init__(self, name: str, decision: Decision,
                 override_roles: List[str] | None = None) -> None:
        self.name = name
        self._decision = decision
        self._override_roles = override_roles or []

    def evaluate(self, perturbation):  # noqa: ANN001
        if self._decision == Decision.OVERRIDE_ALLOWED:
            return Verdict(
                guider=self.name, decision=self._decision,
                confidence=1.0, reason="static",
                override_allowed_by=self._override_roles,
            )
        return Verdict(
            guider=self.name, decision=self._decision,
            confidence=1.0, reason="static",
        )


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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_orchestrator_approves_and_publishes():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.APPROVE)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)

    sig = _signal("INVOICE_INGESTED", {
        "signal_id": "abc", "filename": "f.pdf",
        "vendor": "ACME", "total_amount": "100.00", "job_id": "j1",
    })
    result = asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    assert isinstance(result, OrchestrationResult)
    assert result.published is True
    assert result.cascade_decision == Decision.APPROVE
    assert len(pub.calls) == 1
    channel, payload = pub.calls[0]
    assert channel == sig.target_channel


def test_orchestrator_blocks_and_does_not_publish():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.BLOCK)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)

    sig = _signal("PAYMENT_DEDUP_RISK", {
        "payment_id": "PMT-1", "prior_payment_id": "PMT-0",
        "hard_block": True, "job_id": "j1",
    })
    result = asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    assert result.published is False
    assert result.cascade_decision == Decision.BLOCK
    assert pub.calls == []


def test_orchestrator_escalate_publishes():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.ESCALATE)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)
    sig = _signal("HITL_ESCALATION", {
        "item_id": "I1", "escalation_reason": "x", "escalated_by": "a",
    })
    result = asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    assert result.published is True
    assert result.cascade_decision == Decision.ESCALATE


def test_orchestrator_override_allowed_publishes():
    cascade = GuiderCascade(guiders=[
        StaticGuider("g1", Decision.OVERRIDE_ALLOWED, override_roles=["TREASURER"])
    ])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)
    sig = _signal("POLICY_VIOLATION", {
        "policy_id": "P", "rule_violated": "r", "entity_affected": "e",
    })
    result = asyncio.run(orch.process(sig, role=Role.TREASURER))
    assert result.published is True
    assert result.cascade_decision == Decision.OVERRIDE_ALLOWED


def test_orchestrator_writes_to_ledger_on_block():
    ledger_entries: List[Dict[str, Any]] = []

    def ledger(entry):
        ledger_entries.append(entry)

    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.BLOCK)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub, ledger=ledger)

    sig = _signal("FUND_RESTRICTION_VIOLATION", {
        "fund": "M", "restriction_type": "t", "violation_detail": "d",
        "hard_block": True,
    })
    asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    assert len(ledger_entries) == 1
    assert ledger_entries[0]["decision"] == "BLOCK"


def test_orchestrator_handles_all_10_signals():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.APPROVE)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)

    test_payloads = {
        "INVOICE_INGESTED": {"signal_id": "x", "filename": "f.pdf"},
        "MAPPING_CONFIDENCE_LOW": {"account": "6100", "confidence": 0.5},
        "BUDGET_OVERAGE_RISK": {"account": "6100", "amount": "100", "projected_balance": "200"},
        "FUND_RESTRICTION_VIOLATION": {"fund": "F", "restriction_type": "t", "violation_detail": "d"},
        "JOURNAL_ENTRY_READY": {"je_id": "JE1", "account_entries": [], "amounts": {}},
        "PAYMENT_DEDUP_RISK": {"payment_id": "P1", "prior_payment_id": "P0"},
        "RECONCILIATION_EXCEPTION": {"txn_id": "T1", "amount": "12", "days_unmatched": 5},
        "APPROVAL_DEADLINE_PRESSURE": {"queue_length": 5, "oldest_item_age_days": 2.0},
        "HITL_ESCALATION": {"item_id": "I", "escalation_reason": "r", "escalated_by": "b"},
        "POLICY_VIOLATION": {"policy_id": "P", "rule_violated": "r", "entity_affected": "e"},
    }

    for name, payload in test_payloads.items():
        sig = _signal(name, payload)
        result = asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
        assert result is not None
        assert result.signal_name == name


def test_orchestrator_redacts_before_publishing():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.APPROVE)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)

    # Inject a P3 field into HITL escalation payload — should be redacted out
    sig = _signal("HITL_ESCALATION", {
        "item_id": "I", "escalation_reason": "r", "escalated_by": "b",
        "reviewer_personal_email": "user@personal.com",  # not declared P0/P1
    })
    result = asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    assert result.published is True
    channel, payload = pub.calls[0]
    # The published payload contains a 'payload' field — verify no PII
    distilled = payload.get("payload") or payload
    assert "reviewer_personal_email" not in distilled


def test_orchestrator_emits_resolved_event_after_publish():
    cascade = GuiderCascade(guiders=[StaticGuider("g1", Decision.APPROVE)])
    pub = MockPublisher()
    orch = MembraneOrchestrator(cascade=cascade, publisher=pub)
    sig = _signal("INVOICE_INGESTED", {"signal_id": "x", "filename": "f.pdf"})
    asyncio.run(orch.process(sig, role=Role.FINANCE_STAFF))
    # Two calls: original channel + impact:resolved:<signal_name>
    channels = [c for c, _ in pub.calls]
    assert any(c.startswith("impact:resolved:") for c in channels)
