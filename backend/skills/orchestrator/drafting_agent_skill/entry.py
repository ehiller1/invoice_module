"""Skill entry: invoke MVP drafting_agent via the agent registry."""
from __future__ import annotations
from typing import Any, Dict


def run(inputs: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    # Lazy import to avoid pulling crewai at registry-scan time.
    try:
        from backend.agents import agents as _agents
        agent = getattr(_agents, "drafting_agent", None)
    except Exception as exc:
        return {"ok": False, "agent": "drafting_agent", "error": f"import_failed: {exc}"}
    return {
        "ok": True,
        "agent": "drafting_agent",
        "agent_role": getattr(agent, "role", "Journal Entry Drafter") if agent else None,
        "draft_request": {
            "description": inputs.get("description"),
            "church_id": inputs.get("church_id"),
        },
        "note": "MVP wrapper — actual draft is produced via CrewAI task; this entry exposes the agent to the skill library.",
    }
