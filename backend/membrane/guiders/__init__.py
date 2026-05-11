"""Phase 4: Guider Cascade — 6-position governance layer.

Each guider is a specialized decision-maker that evaluates a perturbation
and returns a Verdict. The GuiderCascade evaluates a perturbation through
all 6 guiders in sequence, stopping at the first BLOCK.

Guiders (in cascade order):
  1. accounting-integrity  — GL mapping / account validity
  2. payment-dedup         — duplicate payment detection
  3. polity-and-deference  — authority / RBAC / approval routing
  4. abundance-and-stewardship — budget / fund restriction validation
  5. witness-and-provenance — provenance + redaction + policy traces
  6. dignity               — policy / compliance gates
"""
from __future__ import annotations

from .base import Decision, Guider, Verdict
from .accounting_integrity import AccountingIntegrityGuider
from .payment_dedup import PaymentDedupGuider
from .polity_and_deference import PolityAndDeferenceGuider
from .abundance_and_stewardship import AbundanceAndStewardshipGuider
from .witness_and_provenance import WitnessAndProvenanceGuider
from .dignity import DignityGuider
from .cascade import CascadeResult, GuiderCascade
from .registry import GuiderRegistry

__all__ = [
    "Decision",
    "Guider",
    "Verdict",
    "AccountingIntegrityGuider",
    "PaymentDedupGuider",
    "PolityAndDeferenceGuider",
    "AbundanceAndStewardshipGuider",
    "WitnessAndProvenanceGuider",
    "DignityGuider",
    "CascadeResult",
    "GuiderCascade",
    "GuiderRegistry",
]
