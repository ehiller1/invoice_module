"""Skill entry: invoke MVP reconciliation_agent."""
from __future__ import annotations
from typing import Any, Dict


def run(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from backend.agents import agents as _agents
        agent = getattr(_agents, "reconciliation_agent", None)
    except Exception as exc:
        return {"ok": False, "agent": "reconciliation_agent", "error": f"import_failed: {exc}"}
    return {
        "ok": True,
        "agent": "reconciliation_agent",
        "agent_role": getattr(agent, "role", "Bank Reconciliation Specialist") if agent else None,
        "request": {
            "church_id": inputs.get("church_id"),
            "account_id": inputs.get("account_id"),
        },
    }
