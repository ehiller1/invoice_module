"""GuiderRegistry — name-based discovery & lifecycle for guiders.

Phase 4 keeps state minimal; Phase 20 will add per-guider learning state.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .base import Guider
from .accounting_integrity import AccountingIntegrityGuider
from .payment_dedup import PaymentDedupGuider
from .polity_and_deference import PolityAndDeferenceGuider
from .abundance_and_stewardship import AbundanceAndStewardshipGuider
from .witness_and_provenance import WitnessAndProvenanceGuider
from .dignity import DignityGuider


class GuiderRegistry:
    """Discovers and constructs guiders by name."""

    _BUILTINS = {
        "accounting-integrity": AccountingIntegrityGuider,
        "payment-dedup": PaymentDedupGuider,
        "polity-and-deference": PolityAndDeferenceGuider,
        "abundance-and-stewardship": AbundanceAndStewardshipGuider,
        "witness-and-provenance": WitnessAndProvenanceGuider,
        "dignity": DignityGuider,
    }

    def __init__(self) -> None:
        self._instances: Dict[str, Guider] = {}
        self._learning_state: Dict[str, Dict] = {}

    def names(self) -> List[str]:
        return list(self._BUILTINS.keys())

    def get(self, name: str) -> Guider:
        if name not in self._BUILTINS:
            raise KeyError(f"Unknown guider: {name}")
        if name not in self._instances:
            self._instances[name] = self._BUILTINS[name]()
        return self._instances[name]

    def register(self, name: str, guider: Guider) -> None:
        """Override a guider with a custom instance (for testing / extension)."""
        self._instances[name] = guider

    def all(self, names: Optional[Iterable[str]] = None) -> List[Guider]:
        names = list(names) if names else self.names()
        return [self.get(n) for n in names]

    # --- Phase 20 stubs (learning state) ---
    def get_learning_state(self, name: str) -> Dict:
        return self._learning_state.setdefault(name, {})

    def update_learning_state(self, name: str, **kwargs) -> None:
        self._learning_state.setdefault(name, {}).update(kwargs)


__all__ = ["GuiderRegistry"]
