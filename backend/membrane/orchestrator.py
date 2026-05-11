"""MembraneOrchestrator — Phase 7 E2E pipeline.

Pipeline:
  ImpactSignal
    -> Distiller (signal-specific payload extraction)
    -> Redactor (RBAC-based field visibility)
    -> GuiderCascade.evaluate()
    -> Publisher (only if decision != BLOCK)
    -> Decision Ledger (Phase 10 integration point)

The orchestrator never raises on publish failure; it returns
OrchestrationResult with `error` populated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from .envelope import ImpactSignal
from .guiders.base import Decision
from .guiders.cascade import CascadeResult, GuiderCascade
from .redactor import PrivacyViolationError, Redactor, Role

from .distiller.invoice_distiller import InvoiceDistiller
from .distiller.payment_distiller import PaymentDistiller
from .distiller.recon_distiller import ReconDistiller
from .distiller.policy_distiller import PolicyDistiller
from .distiller.hitl_distiller import HITLDistiller


logger = logging.getLogger("eime.membrane.orchestrator")


# Map signal_name -> distiller instance (cheap, stateless).
def _default_distiller_map() -> Dict[str, Any]:
    invoice = InvoiceDistiller()
    payment = PaymentDistiller()
    recon = ReconDistiller()
    policy = PolicyDistiller()
    hitl = HITLDistiller()
    return {
        "INVOICE_INGESTED":           invoice,
        "MAPPING_CONFIDENCE_LOW":     invoice,
        "BUDGET_OVERAGE_RISK":        invoice,
        "JOURNAL_ENTRY_READY":        invoice,
        "FUND_RESTRICTION_VIOLATION": policy,
        "POLICY_VIOLATION":           policy,
        "PAYMENT_DEDUP_RISK":         payment,
        "RECONCILIATION_EXCEPTION":   recon,
        "APPROVAL_DEADLINE_PRESSURE": recon,
        "HITL_ESCALATION":            hitl,
    }


@dataclass
class OrchestrationResult:
    signal_name: str
    cascade_decision: Decision
    published: bool
    distilled_payload: Dict[str, Any] = field(default_factory=dict)
    redacted_payload: Dict[str, Any] = field(default_factory=dict)
    cascade_result: Optional[CascadeResult] = None
    audit: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MembraneOrchestrator:
    """Runs the full distill -> redact -> cascade -> publish pipeline."""

    RESOLVED_PREFIX = "impact:resolved:"

    def __init__(
        self,
        cascade: GuiderCascade,
        publisher: Any,
        *,
        redactor: Optional[Redactor] = None,
        distillers: Optional[Dict[str, Any]] = None,
        ledger: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.cascade = cascade
        self.publisher = publisher
        self.redactor = redactor or Redactor()
        self.distillers = distillers or _default_distiller_map()
        self.ledger = ledger

    def _pick_distiller(self, signal_name: str) -> Any:
        d = self.distillers.get(signal_name)
        if d is None:
            # Fallback: use invoice distiller's drop-all behavior, but
            # safer to just pass through whitelisted None.
            return InvoiceDistiller()
        return d

    def _infer_field_classes(self, signal: ImpactSignal, distilled: Dict[str, Any]) -> Dict[str, str]:
        """Map distilled keys to privacy classes.

        Strategy: use the signal's overall privacy_class as a default. Known
        sensitive keys are bumped to higher classes.
        """
        signal_class = signal.privacy_class  # "P0" or "P1" today
        # We treat the envelope's P0 as "public/operational" within the
        # Redactor's P0..P3 schema. Map envelope-level P0/P1 to redactor P0/P1.
        default = signal_class if signal_class in ("P0", "P1") else "P1"

        out: Dict[str, str] = {}
        for k in distilled.keys():
            if k in ("amounts", "amount", "projected_balance", "total_amount"):
                out[k] = "P2"
            elif k in ("ssn", "tax_id", "bank_account_number", "reviewer_personal_email"):
                out[k] = "P3"
            else:
                out[k] = default
        return out

    async def _maybe_await(self, value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value

    async def process(
        self,
        signal: ImpactSignal,
        *,
        role: Role = Role.FINANCE_STAFF,
    ) -> OrchestrationResult:
        signal_name = signal.signal_name
        result = OrchestrationResult(
            signal_name=signal_name,
            cascade_decision=Decision.DISAVOW,
            published=False,
        )

        # ---- Distill ----
        try:
            distiller = self._pick_distiller(signal_name)
            distilled = distiller.distill(signal, context={})
        except Exception as exc:
            logger.exception("distiller failed for %s", signal_name)
            result.error = f"distill_failed: {exc!r}"
            return result
        result.distilled_payload = dict(distilled)

        # ---- Redact ----
        try:
            redacted, audit = self.redactor.redact(
                distilled,
                self._infer_field_classes(signal, distilled),
                role=role,
            )
        except PrivacyViolationError as exc:
            result.error = f"privacy_violation: {exc}"
            return result
        except Exception as exc:
            logger.exception("redactor failed for %s", signal_name)
            result.error = f"redact_failed: {exc!r}"
            return result
        result.redacted_payload = redacted
        result.audit = audit

        # ---- Cascade ----
        try:
            cascade_result = self.cascade.evaluate(signal)
        except Exception as exc:
            logger.exception("cascade failed for %s", signal_name)
            result.error = f"cascade_failed: {exc!r}"
            return result
        result.cascade_result = cascade_result
        result.cascade_decision = cascade_result.final_decision

        # ---- Ledger record (always) ----
        if self.ledger is not None:
            try:
                self.ledger({
                    "signal_name": signal_name,
                    "decision": result.cascade_decision.value,
                    "halted_on": cascade_result.halted_on,
                    "audit": audit,
                    "decided_at": result.decided_at.isoformat(),
                })
            except Exception:
                logger.debug("ledger write failed", exc_info=True)

        # ---- Publish (skip on BLOCK) ----
        if result.cascade_decision == Decision.BLOCK:
            return result

        # Rewrite target_channel to the resolved-mesh channel: post-cascade
        # signals always cross the membrane onto `impact:resolved:<name>`.
        resolved_channel = f"{self.RESOLVED_PREFIX}{signal_name.lower()}"
        try:
            signal.target_channel = resolved_channel
        except Exception:
            pass

        # Build a publishable envelope: original signal dump with the
        # redacted payload swapped in.
        envelope_dump = signal.model_dump(mode="json")
        envelope_dump["payload"] = redacted
        envelope_dump["target_channel"] = resolved_channel

        try:
            await self._maybe_await(
                self.publisher.publish(resolved_channel, envelope_dump)
            )
            result.published = True
        except Exception as exc:
            logger.exception("publish failed for %s", signal_name)
            result.error = f"publish_failed: {exc!r}"
        return result


__all__ = ["MembraneOrchestrator", "OrchestrationResult"]
