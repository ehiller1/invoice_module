"""InvoiceDistiller — distills invoice-pipeline ImpactSignals.

Handles signal names:
  INVOICE_INGESTED, MAPPING_CONFIDENCE_LOW, BUDGET_OVERAGE_RISK,
  POLICY_VIOLATION (legacy alias), FUND_RESTRICTION_VIOLATION,
  JOURNAL_ENTRY_READY.

Whitelists only safe fields. P3 / unknown fields are dropped. P0 sensitive
payloads (e.g. JOURNAL_ENTRY_READY amounts) are redacted at distill time.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .base import Distiller


_FIELD_WHITELIST: Dict[str, tuple] = {
    "INVOICE_INGESTED":           ("signal_id", "filename", "vendor", "total_amount", "job_id"),
    "MAPPING_CONFIDENCE_LOW":     ("account", "confidence", "suggestion", "job_id"),
    "BUDGET_OVERAGE_RISK":        ("account", "amount", "projected_balance", "job_id"),
    "FUND_RESTRICTION_VIOLATION": ("fund", "restriction_type", "violation_detail", "hard_block", "job_id"),
    "JOURNAL_ENTRY_READY":        ("je_id", "account_entries", "job_id"),
    "POLICY_VIOLATION":           ("policy_id", "rule_violated", "entity_affected", "job_id"),
}


class InvoiceDistiller(Distiller):
    """Distiller for invoice-pipeline signals."""

    def distill(self, raw_event: Any, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        signal_name = getattr(raw_event, "signal_name", None)
        payload: Mapping[str, Any] = getattr(raw_event, "payload", {}) or {}

        whitelist = _FIELD_WHITELIST.get(signal_name or "", ())
        out: Dict[str, Any] = {k: payload.get(k) for k in whitelist if k in payload}

        # Special-case JOURNAL_ENTRY_READY: redact amounts (P0 sensitive).
        if signal_name == "JOURNAL_ENTRY_READY":
            if "amounts" in payload:
                out["amounts_redacted"] = True

        out["signal_name"] = signal_name
        return out


__all__ = ["InvoiceDistiller"]
