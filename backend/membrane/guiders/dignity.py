"""Dignity guider — policy / compliance gates."""
from __future__ import annotations

from typing import Callable, List, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


class DignityGuider(Guider):
    """Enforces active policies (e.g. PO>10K requires 3 quotes)."""

    name = "dignity"

    def __init__(
        self,
        policy_evaluator: Optional[Callable[[dict], List[dict]]] = None,
        po_quote_threshold: float = 10_000.0,
        po_quote_min: int = 3,
    ) -> None:
        # policy_evaluator(payload) -> [{"id":..., "violated": bool,
        #                                "severity": "block"|"escalate",
        #                                "exception_approved": bool, "reason": str}, ...]
        self._policy_evaluator = policy_evaluator
        self._po_quote_threshold = po_quote_threshold
        self._po_quote_min = po_quote_min

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)

        # POLICY_VIOLATION signal (perturbation #68)
        if self._signal_name(perturbation) == "POLICY_VIOLATION":
            if payload.get("exception_approved"):
                return Verdict(
                    guider=self.name,
                    decision=Decision.ESCALATE,
                    confidence=0.85,
                    reason="Policy exception previously approved — confirm before posting.",
                )
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason=f"Policy violation: {payload.get('policy_id', 'unknown')}.",
                metadata={"policy_id": payload.get("policy_id")},
            )

        # Built-in: PO over threshold requires N quotes
        if payload.get("type") == "purchase_order" or payload.get("is_po"):
            try:
                amt = float(payload.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            quotes = payload.get("quotes")
            quote_count = len(quotes) if isinstance(quotes, list) else int(payload.get("quote_count", 0) or 0)
            if amt > self._po_quote_threshold and quote_count < self._po_quote_min:
                if payload.get("exception_approved"):
                    return Verdict(
                        guider=self.name,
                        decision=Decision.ESCALATE,
                        confidence=0.9,
                        reason=(
                            f"PO ${amt:,.0f} has {quote_count} quotes (<{self._po_quote_min}); "
                            f"exception previously approved — re-confirm."
                        ),
                    )
                return Verdict(
                    guider=self.name,
                    decision=Decision.BLOCK,
                    confidence=1.0,
                    reason=(
                        f"Policy: PO > ${self._po_quote_threshold:,.0f} requires "
                        f"{self._po_quote_min}+ quotes (got {quote_count})."
                    ),
                    metadata={"amount": amt, "quotes": quote_count},
                )

        # External policy evaluator
        if self._policy_evaluator is not None:
            try:
                results = list(self._policy_evaluator(payload) or [])
            except Exception:
                results = []
            for r in results:
                if not r.get("violated"):
                    continue
                if r.get("exception_approved"):
                    return Verdict(
                        guider=self.name,
                        decision=Decision.ESCALATE,
                        confidence=0.85,
                        reason=f"Policy {r.get('id')} violated; exception approved — re-confirm.",
                        metadata={"policy_id": r.get("id")},
                    )
                severity = r.get("severity", "block")
                if severity == "escalate":
                    return Verdict(
                        guider=self.name,
                        decision=Decision.ESCALATE,
                        confidence=0.9,
                        reason=f"Policy {r.get('id')} violated: {r.get('reason', '')}",
                        metadata={"policy_id": r.get("id")},
                    )
                return Verdict(
                    guider=self.name,
                    decision=Decision.BLOCK,
                    confidence=1.0,
                    reason=f"Policy {r.get('id')} violated: {r.get('reason', '')}",
                    metadata={"policy_id": r.get("id")},
                )

        return Verdict(
            guider=self.name,
            decision=Decision.APPROVE,
            confidence=0.9,
            reason="No active policy violations.",
        )


__all__ = ["DignityGuider"]
