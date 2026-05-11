"""Distiller base class (Phase 1).

A Distiller converts a raw application event into a typed ImpactSignal
envelope. Phase 1 ships only the abstract base; concrete distillers are
introduced in later phases (one per perturbation family).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Mapping, Optional


class Distiller(ABC):
    """Abstract transformer: raw event -> distilled payload dict.

    Subclasses MUST implement `distill`. They should:
      * select an appropriate Perturbation from the registry,
      * scrub or redact sensitive fields per privacy_class,
      * return a dict of safe, whitelisted fields.

    The dict is wrapped into a full ImpactSignal by the orchestrator, which
    supplies the remaining envelope fields (signal_id, event_id, occurred_at,
    target_channel, source, etc.) from the perturbation registry.
    """

    @abstractmethod
    def distill(self, raw_event: Any, context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:  # pragma: no cover - abstract
        """Extract and whitelist safe fields from a raw event."""
        raise NotImplementedError


__all__ = ["Distiller"]
