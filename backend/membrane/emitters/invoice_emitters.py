"""Phase 5 invoice pipeline emitters.

Provides 10 emitter functions, one per Perturbation type (signal IDs 59-68).
Each emitter:
  - Returns None and is a no-op when EMBARK_MEMBRANE_PHASE_5 is OFF.
  - Builds an ImpactSignal v1 envelope when ON.
  - Publishes via the provided publisher (or default local publisher).
  - Catches all exceptions — emissions MUST NOT break the pipeline.

These wrappers are purely additive: they do not mutate pipeline state.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..envelope import ImpactSignal
from ..feature_flags import is_phase_enabled
from ..perturbations import get_perturbation

logger = logging.getLogger("eime.membrane.emitters")

_DEFAULT_SOURCE = "backend.flow"


def _build_signal(
    name: str,
    payload: Dict[str, Any],
    *,
    source: str,
    correlation_id: Optional[str],
) -> ImpactSignal:
    pert = get_perturbation(name)
    return ImpactSignal(
        envelope_version="1",
        signal_id=pert.id,
        signal_name=pert.name,
        event_id=str(uuid.uuid4()),
        occurred_at=datetime.now(tz=timezone.utc),
        privacy_class=pert.privacy_class,  # type: ignore[arg-type]
        crosses_membrane=pert.crosses_membrane,
        target_channel=pert.target_channel,
        payload=payload,
        source=source,
        correlation_id=correlation_id,
        retention=pert.default_retention,
    )


def _run_publish(publisher: Any, signal: ImpactSignal) -> None:
    """Run publisher.publish_signal synchronously or schedule on running loop.

    Never raises — failures logged at debug level.
    """
    try:
        coro = publisher.publish_signal(signal)
        if not asyncio.iscoroutine(coro):
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Fire-and-forget on the running loop.
                asyncio.ensure_future(coro)
                return
        except RuntimeError:
            loop = None
        # No running loop — run to completion synchronously.
        asyncio.run(coro)  # type: ignore[arg-type]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("emitter publish failed: %r", exc)


def _emit(
    name: str,
    payload: Dict[str, Any],
    *,
    publisher: Any,
    source: str,
    correlation_id: Optional[str],
) -> Optional[ImpactSignal]:
    """Common entry point: feature-flag gated, never raises."""
    if not is_phase_enabled(5):
        return None
    try:
        signal = _build_signal(name, payload, source=source, correlation_id=correlation_id)
    except Exception as exc:
        logger.debug("emitter build failed for %s: %r", name, exc)
        return None
    if publisher is not None:
        _run_publish(publisher, signal)
    return signal


# ---------------------------------------------------------------------------
# 10 emitter functions
# ---------------------------------------------------------------------------

def emit_invoice_ingested(
    *,
    signal_id: Optional[str] = None,
    filename: str,
    vendor: Optional[str] = None,
    total_amount: Optional[str] = None,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload: Dict[str, Any] = {
        "signal_id": signal_id or str(uuid.uuid4()),
        "filename": filename,
        "vendor": vendor,
        "total_amount": total_amount,
        "job_id": job_id,
    }
    return _emit("INVOICE_INGESTED", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_mapping_confidence_low(
    *,
    account: str,
    confidence: float,
    suggestion: Optional[str] = None,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "account": account,
        "confidence": float(confidence),
        "suggestion": suggestion,
        "job_id": job_id,
    }
    return _emit("MAPPING_CONFIDENCE_LOW", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_budget_overage_risk(
    *,
    account: str,
    amount: str,
    projected_balance: str,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "account": account,
        "amount": str(amount),
        "projected_balance": str(projected_balance),
        "job_id": job_id,
    }
    return _emit("BUDGET_OVERAGE_RISK", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_fund_restriction_violation(
    *,
    fund: str,
    restriction_type: str,
    violation_detail: str,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "fund": fund,
        "restriction_type": restriction_type,
        "violation_detail": violation_detail,
        "hard_block": True,
        "job_id": job_id,
    }
    return _emit("FUND_RESTRICTION_VIOLATION", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_journal_entry_ready(
    *,
    je_id: str,
    account_entries: Any,
    amounts: Any,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "je_id": je_id,
        "account_entries": account_entries,
        "amounts": amounts,
        "job_id": job_id,
        "sensitive": True,  # P0
    }
    return _emit("JOURNAL_ENTRY_READY", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_payment_dedup_risk(
    *,
    payment_id: str,
    prior_payment_id: str,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "payment_id": payment_id,
        "prior_payment_id": prior_payment_id,
        "hard_block": True,
        "job_id": job_id,
    }
    return _emit("PAYMENT_DEDUP_RISK", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)


def emit_reconciliation_exception(
    *,
    txn_id: str,
    amount: str,
    days_unmatched: int,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "txn_id": txn_id,
        "amount": str(amount),
        "days_unmatched": int(days_unmatched),
    }
    return _emit("RECONCILIATION_EXCEPTION", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id)


def emit_approval_deadline_pressure(
    *,
    queue_length: int,
    oldest_item_age_days: float,
    window_label: Optional[str] = None,
    publisher: Any = None,
    source: str = "backend.scheduler",
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "queue_length": int(queue_length),
        "oldest_item_age_days": float(oldest_item_age_days),
        "window": window_label,
    }
    return _emit("APPROVAL_DEADLINE_PRESSURE", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id)


def emit_hitl_escalation(
    *,
    item_id: str,
    escalation_reason: str,
    escalated_by: str,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "item_id": item_id,
        "escalation_reason": escalation_reason,
        "escalated_by": escalated_by,
    }
    return _emit("HITL_ESCALATION", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or item_id)


def emit_policy_violation(
    *,
    policy_id: str,
    rule_violated: str,
    entity_affected: str,
    job_id: Optional[str] = None,
    publisher: Any = None,
    source: str = _DEFAULT_SOURCE,
    correlation_id: Optional[str] = None,
) -> Optional[ImpactSignal]:
    payload = {
        "policy_id": policy_id,
        "rule_violated": rule_violated,
        "entity_affected": entity_affected,
        "job_id": job_id,
    }
    return _emit("POLICY_VIOLATION", payload, publisher=publisher,
                 source=source, correlation_id=correlation_id or job_id)
