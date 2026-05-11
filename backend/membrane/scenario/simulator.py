"""Phase 15: Scenario Simulator.

What-if simulation engine that projects GL impact of proposed changes.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional

from backend.cards.store import get_card_store
from backend.cards.schemas import PlanCard
from backend.membrane.scenario.scenario_card import ScenarioType

logger = logging.getLogger(__name__)


async def simulate_scenario(
    scenario_name: str,
    scenario_type: ScenarioType,
    assumptions: Dict[str, Any],
    changes: Dict[str, Decimal],
) -> Dict[str, Any]:
    """Simulate a what-if scenario.

    Args:
        scenario_name: Human-readable name
        scenario_type: Scenario type (baseline, optimistic, pessimistic, custom)
        assumptions: Assumptions underlying the projection
        changes: Proposed GL changes {account: delta}

    Returns:
        Scenario Card with projected GL state
    """
    card_store = get_card_store()

    # Get current GL from latest Plan Card
    latest_plans = card_store.query_by_principal("budget-steward")
    base_gl = {}
    if latest_plans:
        latest = latest_plans[-1]
        base_gl = latest.get("accounts", {})

    # Apply changes to base GL
    projected_gl = {k: Decimal(str(v)) for k, v in base_gl.items()}
    for account, delta in changes.items():
        if account in projected_gl:
            projected_gl[account] = projected_gl[account] + Decimal(str(delta))
        else:
            projected_gl[account] = Decimal(str(delta))

    # Analyze impact
    impact_summary = _analyze_impact(base_gl, projected_gl, assumptions)

    # Create Plan Card for scenario (temporary GL projection)
    scenario_id = f"scenario-{scenario_name.lower().replace(' ', '-')}"
    plan_card = PlanCard(
        card_id=f"scenario-{datetime.utcnow().timestamp()}",
        principal="scenario-engine",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        period=datetime.utcnow().isoformat(),
        accounts=projected_gl,
        assumptions={
            **assumptions,
            "scenario_name": scenario_name,
            "scenario_type": scenario_type.value,
            "base_gl": {k: str(v) for k, v in base_gl.items()},
            "changes": {k: str(v) for k, v in changes.items()},
            "scenario_id": scenario_id,
        },
        scenario=scenario_type.value,
    )

    # Write to Card Store
    card_store.write(plan_card, chain=True)

    logger.info(f"Created scenario {scenario_id}")

    return {
        "scenario_id": scenario_id,
        "card_id": plan_card.card_id,
        "name": scenario_name,
        "base_gl": {k: float(v) for k, v in base_gl.items()},
        "projected_gl": {k: float(v) for k, v in projected_gl.items()},
        "changes": {k: float(v) for k, v in changes.items()},
        "impact_summary": impact_summary,
    }


def _analyze_impact(
    base_gl: Dict[str, Decimal],
    projected_gl: Dict[str, Decimal],
    assumptions: Dict[str, Any],
) -> Dict[str, Any]:
    """Analyze impact of scenario changes."""
    total_base = sum(Decimal(str(v)) for v in base_gl.values())
    total_projected = sum(Decimal(str(v)) for v in projected_gl.values())
    net_change = total_projected - total_base

    variance_pct = 0.0
    if total_base != 0:
        variance_pct = float((net_change / total_base * 100))

    # Count affected accounts (convert base_gl to Decimal for comparison)
    affected = sum(
        1 for k in base_gl.keys()
        if Decimal(str(base_gl[k])) != Decimal(str(projected_gl.get(k, 0)))
    )

    return {
        "total_base_gl": float(total_base),
        "total_projected_gl": float(total_projected),
        "net_change": float(net_change),
        "variance_pct": variance_pct,
        "affected_accounts": affected,
        "assumptions_count": len(assumptions),
    }


async def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a scenario by ID."""
    card_store = get_card_store()
    scenarios = card_store.query_by_principal("scenario-engine")

    for scenario in scenarios:
        # Check if scenario_id is at top level or nested in assumptions
        if scenario.get("scenario_id") == scenario_id:
            return scenario
        # Check in assumptions field (where it's actually stored)
        assumptions = scenario.get("assumptions", {})
        if isinstance(assumptions, dict) and assumptions.get("scenario_id") == scenario_id:
            # Return a properly formatted scenario with scenario_id at top level
            result = dict(scenario)
            result["scenario_id"] = scenario_id
            return result

    return None


async def list_scenarios(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List scenarios with optional filtering."""
    card_store = get_card_store()
    scenarios = card_store.query_by_principal("scenario-engine")

    # Filter by status if specified
    if status:
        scenarios = [s for s in scenarios if s.get("status") == status]

    total = len(scenarios)
    scenarios = scenarios[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "scenarios": scenarios,
    }
