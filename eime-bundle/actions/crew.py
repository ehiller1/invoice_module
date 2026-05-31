"""EIME NBA layer — CrewAI Flow scaffold (event-driven).

Six generic archetypes (Sensor, CandidateGenerator, Simulator, Arbiter,
Recommender, OutcomeListener) specialized at runtime by the active domain
SKILL.md under skills/nba/. The Flow expresses cyclic re-evaluation that a
hierarchical Process cannot.

This is a dev-team scaffold. crewai is not installed in this repo, so import
diagnostics are expected (matches the rest of the bundle's crew.py files).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from crewai import Agent, Crew, Task  # noqa: F401  (resolved at dev time)
from crewai.flow.flow import Flow, listen, router, start  # noqa: F401

BUNDLE_ROOT = Path(__file__).resolve().parent
AGENTS = yaml.safe_load(open(BUNDLE_ROOT / "agents.yaml"))["agents"]
TASKS = yaml.safe_load(open(BUNDLE_ROOT / "tasks.yaml"))["tasks"]
SUBS = yaml.safe_load(open(BUNDLE_ROOT / "perturbations" / "subscriptions.yaml"))


def _agent(agent_id: str) -> Dict[str, Any]:
    return next(a for a in AGENTS if a["id"] == agent_id)


def _task(task_id: str) -> Dict[str, Any]:
    return next(t for t in TASKS if t["id"] == task_id)


class EimeNbaFlow(Flow):
    """Event-driven NBA recommender for EIME (domain = nba-eime)."""

    active_nba_domain: str = "nba-eime"

    @start()
    def on_perturbation_received(self) -> Optional[Dict[str, Any]]:
        """NBA Sensor: debounce/dedup/cooldown. Returns trigger_context or None."""
        ...

    @listen(on_perturbation_received)
    def generate_candidates(self, trigger_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Candidate Generator: 3–7 typed candidates from the domain library."""
        ...

    @listen(generate_candidates)
    def simulate_in_parallel(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Simulator: bounded impact projection per candidate + do-nothing baseline."""
        ...

    @listen(simulate_in_parallel)
    def arbitrate(self, projections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Arbiter: four-factor comparative ranking."""
        ...

    @listen(arbitrate)
    def recommend_and_publish(self, ranked: Dict[str, Any]) -> Dict[str, Any]:
        """Recommender: goal-grounded recommendation + ledger write."""
        ...

    @router(recommend_and_publish)
    def route_consumer(self, recommendation: Dict[str, Any]) -> str:
        """Route by consumer type: autonomous agent vs. human UCS card."""
        return "surface_via_ucs_card" if recommendation.get("escalate") else "publish_to_agent_consumer"

    @listen("publish_to_agent_consumer")
    def publish_to_agent_consumer(self, recommendation: Dict[str, Any]) -> None:
        ...

    @listen("surface_via_ucs_card")
    def surface_via_ucs_card(self, recommendation: Dict[str, Any]) -> None:
        """Emits embark.surface.eime.recommendation.v1 to the cabinet surface."""
        ...

    @start()
    def on_outcome_observed(self) -> None:
        """Outcome Listener loop: re-publish observed outcomes for calibration."""
        ...
