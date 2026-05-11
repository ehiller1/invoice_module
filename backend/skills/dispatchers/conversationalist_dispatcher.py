"""Conversationalist archetype dispatcher.

Conversationalists interact with humans (HITL gates, Q&A). The dispatcher
returns a `decisions` object that callers can treat as "approved with no
overrides" by default.
"""
from __future__ import annotations

from typing import Any, Dict

from .base import ArchetypeDispatcher


class ConversationalistDispatcher(ArchetypeDispatcher):
    archetype = "conversationalist"

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = await super()._stub_output(skill_name, inputs, context, record)
        if skill_name == "hitl_invoice_gate":
            base["hitl_decisions"] = {"line_decisions": [], "all_resolved": True}
        elif skill_name == "agent_qa_interface":
            base["answer"] = "stub answer (no HITL invoked)"
        return base


__all__ = ["ConversationalistDispatcher"]
