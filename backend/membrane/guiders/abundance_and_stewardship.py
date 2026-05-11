"""Abundance & Stewardship guider — budget / fund / allocation validation."""
from __future__ import annotations

from typing import Any, Callable, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


class AbundanceAndStewardshipGuider(Guider):
    """Enforces fund restrictions (HARD_BLOCK) and budget variance limits."""

    name = "abundance-and-stewardship"

    def __init__(
        self,
        budget_lookup: Optional[Callable[[str], dict]] = None,
        utilization_warn: float = 0.80,
        variance_block: float = 1.20,  # 120% of budget = hard block
    ) -> None:
        # budget_lookup(category) -> {"budget": x, "spent": y}
        self._budget_lookup = budget_lookup
        self._utilization_warn = utilization_warn
        self._variance_block = variance_block

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)

        # Fund restriction hard block (perturbation #62)
        if self._signal_name(perturbation) == "FUND_RESTRICTION_VIOLATION":
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason="Perturbation flagged FUND_RESTRICTION_VIOLATION (HARD BLOCK).",
            )

        if payload.get("fund_restriction_violation"):
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason=(
                    f"Fund restriction violated: "
                    f"{payload.get('fund_restriction_reason', 'restricted fund used for unrestricted purpose')}."
                ),
                metadata={"fund": payload.get("fund")},
            )

        # Budget variance / utilization
        category = payload.get("budget_category") or payload.get("category")
        amount = payload.get("amount")
        budget_info: Optional[dict] = payload.get("budget_info")
        if budget_info is None and category and self._budget_lookup is not None:
            try:
                budget_info = self._budget_lookup(str(category))
            except Exception:
                budget_info = None

        if budget_info and amount is not None:
            try:
                amt = float(amount)
                budget = float(budget_info.get("budget", 0) or 0)
                spent = float(budget_info.get("spent", 0) or 0)
            except (TypeError, ValueError):
                amt, budget, spent = 0.0, 0.0, 0.0
            if budget > 0:
                projected = (spent + amt) / budget
                if projected >= self._variance_block:
                    return Verdict(
                        guider=self.name,
                        decision=Decision.BLOCK,
                        confidence=0.95,
                        reason=(
                            f"Projected utilization {projected:.0%} exceeds "
                            f"variance block threshold {self._variance_block:.0%}."
                        ),
                        metadata={"projected_utilization": projected},
                    )
                if projected >= self._utilization_warn:
                    return Verdict(
                        guider=self.name,
                        decision=Decision.ESCALATE,
                        confidence=0.85,
                        reason=(
                            f"Projected utilization {projected:.0%} >= warn threshold "
                            f"{self._utilization_warn:.0%}."
                        ),
                        metadata={"projected_utilization": projected},
                    )

        return Verdict(
            guider=self.name,
            decision=Decision.APPROVE,
            confidence=0.9,
            reason="No fund restriction or budget threshold breached.",
        )


__all__ = ["AbundanceAndStewardshipGuider"]
