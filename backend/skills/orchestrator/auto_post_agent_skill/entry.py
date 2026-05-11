"""Skill entry: invoke MVP auto_post_agent."""
from __future__ import annotations
from typing import Any, Dict


def run(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from backend.agents import agents as _agents
        agent = getattr(_agents, "auto_post_agent", None)
    except Exception as exc:
        return {"ok": False, "agent": "auto_post_agent", "error": f"import_failed: {exc}"}
    return {
        "ok": True,
        "agent": "auto_post_agent",
        "agent_role": getattr(agent, "role", "Auto-Posting Agent") if agent else None,
        "request": {"je_draft": inputs.get("je_draft"), "recurring_id": inputs.get("recurring_id")},
    }
