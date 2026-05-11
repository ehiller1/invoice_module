"""Embark Membrane Integration — Phase 1 Foundation.

Substrate layer: perturbation registry, ImpactSignal envelope, Distiller base,
feature flags. Purely additive; no existing code is modified.
"""

from backend.membrane.envelope import ImpactSignal
from backend.membrane.perturbations import (
    PERTURBATIONS,
    Perturbation,
    get_perturbation,
)

__all__ = ["ImpactSignal", "PERTURBATIONS", "Perturbation", "get_perturbation"]
