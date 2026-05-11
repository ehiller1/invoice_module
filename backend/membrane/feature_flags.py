"""Feature flags for the Embark Membrane integration.

One flag per phase, keyed to FR-IM references in PLAN-membrane-integration.md.
Flags default to environment overrides via `EMBARK_MEMBRANE_PHASE_<N>` env vars
(truthy values: "1", "true", "yes"). Phase 1 (substrate) defaults ON; all
later phases default OFF until their implementation lands.
"""
from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


# FR-IM cross-reference table: phase -> requirement spec anchor.
FR_IM_REFERENCES = {
    1: "FR-IM-1: Substrate (perturbation registry, envelope, distiller base, flags)",
    2: "FR-IM-2: Distiller implementations + emitter pipeline",
    3: "FR-IM-3: Membrane bus + privacy gate (P0/P1 enforcement)",
    4: "FR-IM-4: External observer adapters (mesh, peers)",
    5: "FR-IM-5: Scheduler perturbations + deadline pressure",
    6: "FR-IM-6: Audit, retention, and replay",
}

PHASE_1_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_1", default=True)
PHASE_2_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_2", default=False)
PHASE_3_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_3", default=False)
PHASE_4_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_4", default=False)
PHASE_5_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_5", default=False)
PHASE_6_ENABLED: bool = _env_flag("EMBARK_MEMBRANE_PHASE_6", default=False)

_PHASE_MAP = {
    1: PHASE_1_ENABLED,
    2: PHASE_2_ENABLED,
    3: PHASE_3_ENABLED,
    4: PHASE_4_ENABLED,
    5: PHASE_5_ENABLED,
    6: PHASE_6_ENABLED,
}


def is_phase_enabled(phase: int) -> bool:
    """Return True iff the given phase's feature flag is on."""
    return bool(_PHASE_MAP.get(phase, False))


__all__ = [
    "FR_IM_REFERENCES",
    "PHASE_1_ENABLED",
    "PHASE_2_ENABLED",
    "PHASE_3_ENABLED",
    "PHASE_4_ENABLED",
    "PHASE_5_ENABLED",
    "PHASE_6_ENABLED",
    "is_phase_enabled",
]
