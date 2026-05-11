"""Payment Dedup guider — detects duplicate payments."""
from __future__ import annotations

from typing import Callable, List, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


class PaymentDedupGuider(Guider):
    """Blocks exact duplicates within a window; escalates near-duplicates."""

    name = "payment-dedup"

    def __init__(
        self,
        history_lookup: Optional[Callable[[str, float], List[dict]]] = None,
        window_days: int = 7,
    ) -> None:
        # history_lookup(vendor, amount) -> list of prior payments (dicts)
        self._history_lookup = history_lookup
        self._window_days = window_days

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)

        # Signal-driven hard block (perturbation #64 PAYMENT_DEDUP_RISK)
        if self._signal_name(perturbation) == "PAYMENT_DEDUP_RISK":
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=0.99,
                reason="Perturbation flagged as PAYMENT_DEDUP_RISK (hard block).",
            )

        # Explicit duplicate flags
        if payload.get("is_exact_duplicate"):
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason="Exact duplicate payment detected (same vendor+amount+date).",
            )

        # Probable duplicate via supplied history
        vendor = payload.get("vendor") or payload.get("vendor_id")
        amount = payload.get("amount")
        if vendor and amount is not None and self._history_lookup is not None:
            try:
                priors = self._history_lookup(str(vendor), float(amount)) or []
            except Exception:
                priors = []
            within_window = [
                p for p in priors
                if int(p.get("days_ago", 9999)) <= self._window_days
            ]
            if within_window:
                # Same vendor+amount within window => escalate (probable dup)
                return Verdict(
                    guider=self.name,
                    decision=Decision.ESCALATE,
                    confidence=0.8,
                    reason=(
                        f"Possible duplicate: {len(within_window)} prior payment(s) "
                        f"to {vendor} for {amount} within {self._window_days} days."
                    ),
                    metadata={"prior_count": len(within_window)},
                )

        # Probable_duplicate flag set by caller (e.g. fraud_detector)
        if payload.get("probable_duplicate"):
            return Verdict(
                guider=self.name,
                decision=Decision.ESCALATE,
                confidence=float(payload.get("dup_confidence", 0.75)),
                reason="Probable duplicate flagged by upstream detector.",
            )

        return Verdict(
            guider=self.name,
            decision=Decision.APPROVE,
            confidence=0.85,
            reason="No duplicate signals detected.",
        )


__all__ = ["PaymentDedupGuider"]
