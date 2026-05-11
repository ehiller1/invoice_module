"""Skill entry: invoke MVP compliance_agent."""
from __future__ import annotations
from typing import Any, Dict


def run(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from backend.agents import agents as _agents
        agent = getattr(_agents, "compliance_agent", None)
    except Exception as exc:
        return {"ok": False, "agent": "compliance_agent", "error": f"import_failed: {exc}"}
    return {
        "ok": True,
        "agent": "compliance_agent",
        "agent_role": getattr(agent, "role", "Compliance Officer & Policy Enforcer") if agent else None,
        "request": {"je_draft": inputs.get("je_draft"), "church_id": inputs.get("church_id")},
    }
