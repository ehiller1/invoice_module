"""Skill entry: invoke MVP advisor_agent."""
from __future__ import annotations
from typing import Any, Dict


def run(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from backend.agents import agents as _agents
        agent = getattr(_agents, "advisor_agent", None)
    except Exception as exc:
        return {"ok": False, "agent": "advisor_agent", "error": f"import_failed: {exc}"}
    return {
        "ok": True,
        "agent": "advisor_agent",
        "agent_role": getattr(agent, "role", "Financial Advisor") if agent else None,
        "request": {"question": inputs.get("question"), "church_id": inputs.get("church_id")},
    }
