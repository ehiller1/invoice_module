"""Base Guider class and Verdict schema (Phase 4).

A Guider is an abstract decision-maker that evaluates a perturbation
(an ImpactSignal envelope or a dict-shaped proposal) and returns a Verdict.

Verdicts:
  APPROVE          — guider sees no issue
  BLOCK            — hard stop; cascade halts here unless overridden
  ESCALATE         — needs human / superior review but is not a hard block
  OVERRIDE_ALLOWED — block-equivalent, but specific principals listed in
                     `override_allowed_by` may override
  DISAVOW          — guider explicitly refuses to opine (e.g. missing
                     context); treated as soft-skip by the cascade
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional


class Decision(str, Enum):
    APPROVE = "APPROVE"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    OVERRIDE_ALLOWED = "OVERRIDE_ALLOWED"
    DISAVOW = "DISAVOW"


@dataclass(frozen=True)
class Verdict:
    """A guider's structured opinion on a perturbation."""

    guider: str
    decision: Decision
    confidence: float  # 0.0 .. 1.0
    reason: str
    override_allowed_by: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0,1], got {self.confidence}"
            )
        if not isinstance(self.decision, Decision):
            raise TypeError(
                f"decision must be a Decision enum, got {type(self.decision)!r}"
            )
        if self.decision == Decision.OVERRIDE_ALLOWED and not self.override_allowed_by:
            raise ValueError(
                "OVERRIDE_ALLOWED verdicts must list at least one principal in override_allowed_by"
            )

    @property
    def is_hard_block(self) -> bool:
        """True if cascade should halt (BLOCK without overrides)."""
        return self.decision == Decision.BLOCK

    @property
    def is_blocking(self) -> bool:
        """BLOCK or OVERRIDE_ALLOWED both prevent default approval."""
        return self.decision in (Decision.BLOCK, Decision.OVERRIDE_ALLOWED)

    def can_override(self, principal_roles: List[str]) -> bool:
        """Return True if any role can override this verdict."""
        if self.decision != Decision.OVERRIDE_ALLOWED:
            return False
        return any(r in self.override_allowed_by for r in principal_roles)


PerturbationLike = Mapping[str, Any]


class Guider(ABC):
    """Abstract base class for the 6-position cascade."""

    name: str = ""

    @abstractmethod
    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        """Inspect a perturbation/proposal and emit a Verdict."""
        raise NotImplementedError

    def _payload(self, perturbation: PerturbationLike) -> Dict[str, Any]:
        """Extract the payload dict whether perturbation is an ImpactSignal
        Pydantic instance, an ImpactSignal-shaped mapping, or a bare payload."""
        if perturbation is None:
            return {}
        # Pydantic v2 ImpactSignal exposes .payload
        payload = getattr(perturbation, "payload", None)
        if payload is not None:
            return dict(payload)
        if isinstance(perturbation, Mapping):
            if "payload" in perturbation and isinstance(perturbation["payload"], Mapping):
                return dict(perturbation["payload"])
            return dict(perturbation)
        return {}

    def _signal_name(self, perturbation: PerturbationLike) -> Optional[str]:
        name = getattr(perturbation, "signal_name", None)
        if name:
            return name
        if isinstance(perturbation, Mapping):
            return perturbation.get("signal_name")
        return None


__all__ = ["Decision", "Verdict", "Guider", "PerturbationLike"]
