"""Phase 5 emitter package — wraps perturbation signal construction and publishing.

Each emitter is a thin function:
  - Builds an ImpactSignal envelope from a Perturbation registry entry.
  - Publishes it via a Publisher when feature flag is enabled.
  - Is a no-op (returns None) when feature flag is OFF.

Emitters NEVER raise — failures are swallowed to preserve pipeline invariants.
"""
from __future__ import annotations

from .invoice_emitters import (
    emit_invoice_ingested,
    emit_mapping_confidence_low,
    emit_budget_overage_risk,
    emit_fund_restriction_violation,
    emit_journal_entry_ready,
    emit_payment_dedup_risk,
    emit_reconciliation_exception,
    emit_approval_deadline_pressure,
    emit_hitl_escalation,
    emit_policy_violation,
)

__all__ = [
    "emit_invoice_ingested",
    "emit_mapping_confidence_low",
    "emit_budget_overage_risk",
    "emit_fund_restriction_violation",
    "emit_journal_entry_ready",
    "emit_payment_dedup_risk",
    "emit_reconciliation_exception",
    "emit_approval_deadline_pressure",
    "emit_hitl_escalation",
    "emit_policy_violation",
]
