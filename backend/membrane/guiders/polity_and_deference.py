"""Polity & Deference guider — authority / RBAC / approval routing."""
from __future__ import annotations

from typing import Callable, List, Optional

from .base import Decision, Guider, PerturbationLike, Verdict


# Default delegation bands (USD). Principals with these roles may approve
# amounts up to the listed cap. Treasurers/admins always override.
DEFAULT_DELEGATION_BANDS = {
    "VIEWER": 0.0,
    "FINANCE_STAFF": 5_000.0,
    "FINANCE_MANAGER": 25_000.0,
    "TREASURER": float("inf"),
    "ADMIN": float("inf"),
}

OVERRIDE_PRINCIPALS = ["TREASURER", "ADMIN"]


class PolityAndDeferenceGuider(Guider):
    """Checks whether the proposing principal has authority for this action."""

    name = "polity-and-deference"

    def __init__(
        self,
        delegation_bands: Optional[dict] = None,
        chain_resolver: Optional[Callable[[float, List[str]], List[str]]] = None,
    ) -> None:
        self._bands = delegation_bands or DEFAULT_DELEGATION_BANDS
        self._chain_resolver = chain_resolver

    def _max_authority(self, roles: List[str]) -> float:
        if not roles:
            return 0.0
        return max((self._bands.get(r, 0.0) for r in roles), default=0.0)

    def evaluate(self, perturbation: PerturbationLike) -> Verdict:
        payload = self._payload(perturbation)
        roles = list(payload.get("principal_roles") or [])
        amount = payload.get("amount")
        try:
            amount_f = float(amount) if amount is not None else 0.0
        except (TypeError, ValueError):
            amount_f = 0.0

        if not roles:
            return Verdict(
                guider=self.name,
                decision=Decision.BLOCK,
                confidence=1.0,
                reason="No principal_roles supplied; cannot authorize action.",
            )

        cap = self._max_authority(roles)

        if amount_f <= cap:
            return Verdict(
                guider=self.name,
                decision=Decision.APPROVE,
                confidence=0.95,
                reason=f"Principal authority cap ({cap}) covers amount ({amount_f}).",
                metadata={"authority_cap": cap, "amount": amount_f},
            )

        # Over band — try to escalate via chain resolver
        if self._chain_resolver is not None:
            try:
                chain = list(self._chain_resolver(amount_f, roles) or [])
            except Exception:
                chain = []
            if chain:
                return Verdict(
                    guider=self.name,
                    decision=Decision.ESCALATE,
                    confidence=0.9,
                    reason=(
                        f"Amount {amount_f} exceeds principal cap {cap}; "
                        f"escalate to {chain[0]}."
                    ),
                    override_allowed_by=OVERRIDE_PRINCIPALS,
                    metadata={"approval_chain": chain},
                )

        # No chain available: override-allowed by treasurer/admin
        return Verdict(
            guider=self.name,
            decision=Decision.OVERRIDE_ALLOWED,
            confidence=0.9,
            reason=(
                f"Amount {amount_f} exceeds principal authority cap {cap}; "
                f"only TREASURER/ADMIN may override."
            ),
            override_allowed_by=OVERRIDE_PRINCIPALS,
            metadata={"authority_cap": cap, "amount": amount_f},
        )


__all__ = ["PolityAndDeferenceGuider", "DEFAULT_DELEGATION_BANDS", "OVERRIDE_PRINCIPALS"]
