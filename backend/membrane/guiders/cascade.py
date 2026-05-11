"""GuiderCascade — orchestrates the 6-position cascade."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .base import Decision, Guider, PerturbationLike, Verdict
from .accounting_integrity import AccountingIntegrityGuider
from .payment_dedup import PaymentDedupGuider
from .polity_and_deference import PolityAndDeferenceGuider
from .abundance_and_stewardship import AbundanceAndStewardshipGuider
from .witness_and_provenance import WitnessAndProvenanceGuider
from .dignity import DignityGuider


CASCADE_ORDER = (
    "accounting-integrity",
    "payment-dedup",
    "polity-and-deference",
    "abundance-and-stewardship",
    "witness-and-provenance",
    "dignity",
)


@dataclass
class CascadeResult:
    """Aggregate result from running all six guiders."""

    verdicts: List[Verdict] = field(default_factory=list)
    halted_on: Optional[str] = None  # guider.name that caused hard stop
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def final_decision(self) -> Decision:
        """Aggregate final decision across the cascade."""
        if any(v.decision == Decision.BLOCK for v in self.verdicts):
            return Decision.BLOCK
        if any(v.decision == Decision.OVERRIDE_ALLOWED for v in self.verdicts):
            return Decision.OVERRIDE_ALLOWED
        if any(v.decision == Decision.ESCALATE for v in self.verdicts):
            return Decision.ESCALATE
        # DISAVOW alone is treated as APPROVE for aggregation
        if all(v.decision in (Decision.APPROVE, Decision.DISAVOW) for v in self.verdicts):
            return Decision.APPROVE
        return Decision.ESCALATE

    @property
    def approved(self) -> bool:
        return self.final_decision == Decision.APPROVE

    @property
    def blocked(self) -> bool:
        return self.final_decision == Decision.BLOCK

    def overrides_required(self) -> List[str]:
        """Union of override_allowed_by lists across blocking verdicts."""
        out: List[str] = []
        for v in self.verdicts:
            if v.decision == Decision.OVERRIDE_ALLOWED:
                for r in v.override_allowed_by:
                    if r not in out:
                        out.append(r)
        return out

    def can_be_overridden_by(self, principal_roles: List[str]) -> bool:
        """True if all OVERRIDE_ALLOWED verdicts can be overridden by the
        given roles, and there are no hard BLOCKs."""
        if self.blocked:
            return False
        for v in self.verdicts:
            if v.decision == Decision.OVERRIDE_ALLOWED and not v.can_override(principal_roles):
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_decision": self.final_decision.value,
            "halted_on": self.halted_on,
            "decided_at": self.decided_at.isoformat(),
            "verdicts": [
                {
                    "guider": v.guider,
                    "decision": v.decision.value,
                    "confidence": v.confidence,
                    "reason": v.reason,
                    "override_allowed_by": list(v.override_allowed_by),
                    "metadata": dict(v.metadata),
                }
                for v in self.verdicts
            ],
        }


class GuiderCascade:
    """Evaluates a perturbation through the 6-position guider cascade.

    Behavior:
      - Runs guiders in CASCADE_ORDER.
      - Stops at the first BLOCK verdict (hard stop) and records `halted_on`.
      - Collects all verdicts up to and including the halt verdict.
      - Optionally emits the cascade result via a `sink` callable
        (e.g. publishing to `impact:resolved:cascade_verdict`).
      - Optionally records the result in a Decision Ledger (Phase 10).
    """

    DEFAULT_CHANNEL = "impact:resolved:cascade_verdict"

    def __init__(
        self,
        guiders: Optional[List[Guider]] = None,
        sink: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        ledger: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._guiders: List[Guider] = guiders if guiders is not None else self._default_guiders()
        self._guider_by_name = {g.name: g for g in self._guiders}
        self._sink = sink
        self._ledger = ledger

    @staticmethod
    def _default_guiders() -> List[Guider]:
        return [
            AccountingIntegrityGuider(),
            PaymentDedupGuider(),
            PolityAndDeferenceGuider(),
            AbundanceAndStewardshipGuider(),
            WitnessAndProvenanceGuider(),
            DignityGuider(),
        ]

    @property
    def order(self) -> List[str]:
        return [g.name for g in self._guiders]

    def evaluate(self, perturbation: PerturbationLike) -> CascadeResult:
        result = CascadeResult()
        for guider in self._guiders:
            verdict = guider.evaluate(perturbation)
            result.verdicts.append(verdict)
            if verdict.decision == Decision.BLOCK:
                result.halted_on = guider.name
                break

        self._emit(result)
        self._record(result, perturbation)
        return result

    def _emit(self, result: CascadeResult) -> None:
        if self._sink is None:
            return
        try:
            self._sink(self.DEFAULT_CHANNEL, result.to_dict())
        except Exception:
            # Sinks must never break the cascade.
            pass

    def _record(self, result: CascadeResult, perturbation: PerturbationLike) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger({
                "perturbation": getattr(perturbation, "signal_name", None)
                or (perturbation.get("signal_name") if isinstance(perturbation, dict) else None),
                "result": result.to_dict(),
            })
        except Exception:
            pass


__all__ = ["GuiderCascade", "CascadeResult", "CASCADE_ORDER"]
