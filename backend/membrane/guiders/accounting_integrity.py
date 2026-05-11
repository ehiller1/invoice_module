"""Accounting Integrity guider — validates GL mappings & account structure."""
from __future__ import annotations

from typing import Any, Callable, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


class AccountingIntegrityGuider(Guider):
    """Blocks invalid GL accounts, circular allocations, missing mappings."""

    name = "accounting-integrity"

    def __init__(
        self,
        account_validator: Optional[Callable[[str], bool]] = None,
        min_mapping_confidence: float = 0.5,
    ) -> None:
        self._account_validator = account_validator
        self._min_mapping_confidence = min_mapping_confidence

    def _account_is_valid(self, account: Any) -> bool:
        if not account:
            return False
        if self._account_validator is not None:
            try:
                return bool(self._account_validator(str(account)))
            except Exception:
                return False
        # Default heuristic: GL accounts are non-empty alphanumeric strings.
        s = str(account)
        return s.replace("-", "").replace("_", "").isalnum() and len(s) >= 3

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)

        # Circular allocation flag
        if payload.get("circular_allocation"):
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason="Circular allocation detected in proposed journal entry.",
            )

        # GL account validation
        gl_accounts = payload.get("gl_accounts") or []
        if isinstance(gl_accounts, (str, int)):
            gl_accounts = [gl_accounts]
        for acct in gl_accounts:
            if not self._account_is_valid(acct):
                return Verdict(
                    guider=self.name,
                    decision=Decision.BLOCK,
                    confidence=0.95,
                    reason=f"Invalid GL account: {acct!r}",
                    metadata={"invalid_account": acct},
                )

        # Mapping confidence (from gl_mapper)
        conf = payload.get("mapping_confidence")
        if conf is not None:
            try:
                conf_f = float(conf)
            except (TypeError, ValueError):
                conf_f = 0.0
            if conf_f < self._min_mapping_confidence:
                return Verdict(
                    guider=self.name,
                    decision=Decision.ESCALATE,
                    confidence=1.0 - conf_f,
                    reason=f"Low GL mapping confidence ({conf_f:.2f} < {self._min_mapping_confidence}).",
                    metadata={"mapping_confidence": conf_f},
                )

        return Verdict(
            guider=self.name,
            decision=Decision.APPROVE,
            confidence=0.9,
            reason="GL accounts valid; mapping confidence acceptable.",
        )


__all__ = ["AccountingIntegrityGuider"]
