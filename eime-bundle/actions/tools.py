"""EIME NBA layer — tool stubs.

Dev-team scaffolds. The runtime binds these to the Redis mesh
(redis-mesh-wiring outputs) and the decision ledger (backend/decision_ledger.py).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def mesh_subscriber(channels: Iterable[str]) -> Iterable[Dict[str, Any]]:
    """Redis Streams consumer for subscribed perturbations (subscriptions.yaml)."""
    raise NotImplementedError("Bind to the Redis mesh consumer group from mesh/mesh_config.yaml.")


def mesh_publisher(perturbation: Dict[str, Any]) -> str:
    """Redis Streams producer for embark.surface.eime.recommendation.v1."""
    raise NotImplementedError("Bind to the Redis mesh producer from mesh/mesh_config.yaml.")


def ledger_reader(window_minutes: int = 60) -> List[Dict[str, Any]]:
    """Read recent Decision Ledger entries for cooldown/context."""
    raise NotImplementedError("Bind to backend/decision_ledger.py read API.")


def ledger_writer(entry: Dict[str, Any]) -> str:
    """Write the NBA audit-trail entry. Always called, regardless of consumer."""
    raise NotImplementedError("Bind to backend/decision_ledger.py write API.")


def twin_simulator(candidate: Dict[str, Any], depth: int = 2) -> Dict[str, Any]:
    """Optional per-domain digital twin. EIME default depth is 2 (no twin registered)."""
    raise NotImplementedError(
        "EIME nba-eime domain uses bounded depth-2 lookahead without a twin simulator. "
        "Register a twin and raise simulation_depth in skills/nba/nba-eime.md to enable."
    )
