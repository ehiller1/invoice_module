"""Perturbation registry for the Embark Membrane (Phase 1).

Each perturbation is a typed signal the application emits onto the membrane.
Phase 1 registers signals 59-68 (10 total). Subsequent phases extend the
registry but never mutate existing entries.

Privacy classes (FR-IM-PRIV):
  P0 — sensitive (amounts, PII); visible only to FINANCE_STAFF+ roles
  P1 — operational (status, counts, timing); broadly visible

`crosses_membrane=True` means the signal is allowed to leave the local
distiller and reach external observers (mesh, peers). `False` means the
signal must remain inside the local membrane.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

PRIVACY_CLASSES = ("P0", "P1")


@dataclass(frozen=True)
class Perturbation:
    """Registry entry describing a single membrane signal."""

    id: int
    name: str
    privacy_class: str  # "P0" | "P1"
    crosses_membrane: bool
    default_retention: str
    target_channel: str
    description: str = ""

    @property
    def sensitive(self) -> bool:
        """P0 signals carry sensitive payloads (amounts, PII)."""
        return self.privacy_class == "P0"

    def __post_init__(self) -> None:
        if self.privacy_class not in PRIVACY_CLASSES:
            raise ValueError(
                f"privacy_class must be one of {PRIVACY_CLASSES}, got {self.privacy_class!r}"
            )


def _channel(name: str, crosses: bool) -> str:
    scope = "external" if crosses else "proposed"
    return f"impact:{scope}:{name.lower()}"


_REGISTRY_SPEC = [
    # (id, name, privacy, crosses, retention, description)
    (59, "INVOICE_INGESTED",          "P1", False, "30d",
     "A new invoice has entered the ingestion pipeline."),
    (60, "MAPPING_CONFIDENCE_LOW",    "P1", False, "30d",
     "Mapping agent produced a low-confidence GL suggestion."),
    (61, "BUDGET_OVERAGE_RISK",       "P1", False, "90d",
     "Proposed posting would breach a configured budget threshold."),
    (62, "FUND_RESTRICTION_VIOLATION","P1", False, "365d",
     "HARD BLOCK: posting violates a fund restriction policy."),
    (63, "JOURNAL_ENTRY_READY",       "P0", False, "365d",
     "Journal entry assembled and ready for review; amounts visible to FINANCE_STAFF+ only."),
    (64, "PAYMENT_DEDUP_RISK",        "P1", False, "180d",
     "HARD BLOCK: candidate payment matches a possible duplicate."),
    (65, "RECONCILIATION_EXCEPTION",  "P1", True,  "180d",
     "Bank reconciliation produced an unresolved exception."),
    (66, "APPROVAL_DEADLINE_PRESSURE","P1", True,  "30d",
     "Scheduler-emitted: pending approval is nearing its SLA deadline."),
    (67, "HITL_ESCALATION",           "P1", True,  "180d",
     "Human-in-the-loop review requested or escalated."),
    (68, "POLICY_VIOLATION",          "P1", True,  "365d",
     "A policy gate fired against a proposed action."),
]


def _build_registry() -> Dict[int, Perturbation]:
    out: Dict[int, Perturbation] = {}
    for pid, name, priv, crosses, retention, desc in _REGISTRY_SPEC:
        # Special-case channel name for INVOICE_INGESTED per spec.
        if name == "INVOICE_INGESTED":
            channel = "impact:proposed:invoice_ingested"
        else:
            channel = _channel(name, crosses)
        out[pid] = Perturbation(
            id=pid,
            name=name,
            privacy_class=priv,
            crosses_membrane=crosses,
            default_retention=retention,
            target_channel=channel,
            description=desc,
        )
    return out


PERTURBATIONS: Dict[int, Perturbation] = _build_registry()
_BY_NAME: Dict[str, Perturbation] = {p.name: p for p in PERTURBATIONS.values()}


def get_perturbation(name_or_id) -> Perturbation:
    """Lookup a perturbation by name (str) or numeric id (int)."""
    if isinstance(name_or_id, int):
        if name_or_id not in PERTURBATIONS:
            raise KeyError(name_or_id)
        return PERTURBATIONS[name_or_id]
    if name_or_id not in _BY_NAME:
        raise KeyError(name_or_id)
    return _BY_NAME[name_or_id]


__all__ = [
    "PRIVACY_CLASSES",
    "Perturbation",
    "PERTURBATIONS",
    "get_perturbation",
]
