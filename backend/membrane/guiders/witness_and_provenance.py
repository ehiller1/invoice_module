"""Witness & Provenance guider — provenance + redaction + risk traces."""
from __future__ import annotations

from typing import Callable, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


class WitnessAndProvenanceGuider(Guider):
    """Blocks high-risk actions lacking explanation; records who/when/what."""

    name = "witness-and-provenance"

    def __init__(
        self,
        risk_assessor: Optional[Callable[[dict], float]] = None,
        high_risk_threshold: float = 0.7,
        ledger_recorder: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._risk_assessor = risk_assessor
        self._high_risk_threshold = high_risk_threshold
        self._ledger_recorder = ledger_recorder

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)

        principal = payload.get("principal") or payload.get("principal_id")
        explanation = payload.get("explanation") or payload.get("rationale")

        # Missing provenance is itself a soft issue
        if not principal:
            return Verdict(
                guider=self.name,
                decision=Decision.ESCALATE,
                confidence=0.85,
                reason="No principal recorded — provenance incomplete.",
            )

        # Compute / read risk score
        risk = payload.get("risk_score")
        if risk is None and self._risk_assessor is not None:
            try:
                risk = float(self._risk_assessor(payload))
            except Exception:
                risk = None
        try:
            risk_f = float(risk) if risk is not None else 0.0
        except (TypeError, ValueError):
            risk_f = 0.0

        if risk_f >= self._high_risk_threshold and not explanation:
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=min(1.0, risk_f),
                reason=(
                    f"High risk ({risk_f:.2f}) without an explanation/rationale — "
                    f"provenance insufficient."
                ),
                metadata={"risk_score": risk_f},
            )

        # Record provenance regardless (no-op if no ledger)
        if self._ledger_recorder is not None:
            try:
                self._ledger_recorder({
                    "principal": principal,
                    "risk_score": risk_f,
                    "explanation": explanation,
                    "signal": self._signal_name(perturbation),
                })
            except Exception:
                pass

        if risk_f >= self._high_risk_threshold:
            return Verdict(
                guider=self.name,
                decision=Decision.ESCALATE,
                confidence=risk_f,
                reason=f"High risk ({risk_f:.2f}) but explanation supplied — escalate for witness review.",
                metadata={"risk_score": risk_f},
            )

        return Verdict(
            guider=self.name,
            decision=Decision.APPROVE,
            confidence=1.0 - risk_f,
            reason="Provenance recorded; risk within tolerance.",
            metadata={"risk_score": risk_f},
        )


__all__ = ["WitnessAndProvenanceGuider"]
