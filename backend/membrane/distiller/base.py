"""Distiller base class (Phase 1).

A Distiller converts a raw application event into a typed ImpactSignal
envelope. Phase 1 ships only the abstract base; concrete distillers are
introduced in later phases (one per perturbation family).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.membrane.envelope import ImpactSignal


class Distiller(ABC):
    """Abstract transformer: raw event -> ImpactSignal.

    Subclasses MUST implement `distill`. They should:
      * select an appropriate Perturbation from the registry,
      * scrub or redact sensitive fields per privacy_class,
      * return a fully-formed ImpactSignal validated against schema v1.
    """

    @abstractmethod
    def distill(self, raw_event: Any) -> ImpactSignal:  # pragma: no cover - abstract
        """Transform a raw event into a validated ImpactSignal envelope."""
        raise NotImplementedError


__all__ = ["Distiller"]
