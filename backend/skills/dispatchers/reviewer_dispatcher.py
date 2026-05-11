"""Reviewer archetype dispatcher.

Reviewers validate, score, and escalate. They never mutate accounting state;
they only return verdicts that downstream stages can act on.
"""
from __future__ import annotations

from typing import Any, Dict

from .base import ArchetypeDispatcher


class ReviewerDispatcher(ArchetypeDispatcher):
    archetype = "reviewer"

    async def _stub_output(
        self,
        skill_name: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        record: Dict[str, Any],
    ) -> Dict[str, Any]:
        base = await super()._stub_output(skill_name, inputs, context, record)
        if skill_name == "allocation_reviewer":
            base["reviewed_allocations"] = {
                "overall_verdict": "APPROVED",
                "escalation_items": [],
                "revision_items": [],
                "review_notes": "stub: no violations detected",
            }
        elif skill_name == "risk_assessor":
            base["risk_assessment"] = {"risk_level": "LOW", "risk_score": 0.0}
        elif skill_name == "fraud_detector":
            base["fraud_assessment"] = {"fraud_level": "NONE", "fraud_score": 0.0, "signals": []}
        return base


__all__ = ["ReviewerDispatcher"]
